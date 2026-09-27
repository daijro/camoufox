r"""
Page-observable differences from stock Firefox found in review, each checked as
an invariant stock Firefox 152 holds:

  canvas-system-font  ctx.font = 'caption' (and the other CSS2 system-font
                      keywords) reads back the keyword, not '10px sans-serif'
  webgl-state         pixelStorei / hint / {alpha:false} read back what the page
                      set; UNMASKED_RENDERER_WEBGL without the extension is null
                      with INVALID_ENUM
  webrtc-no-servers   with webrtc:ipv4 spoofed, a connection with no iceServers
                      gathers no srflx, and getStats() ids carry no "camou"
  gum-fake            getUserMedia({audio: true, fake: true}) resolves without a
                      prompt
  storage-partition   a cross-site iframe's document.hasStorageAccess() is false
  wheel-default       page.mouse.wheel(0, 300) delivers the delta the caller
                      asked for: one event, deltaMode 0, deltaY 300
  wheel-notches       the same scroll with humanize=True arrives as 3 events
                      with wheelDeltaY a multiple of 120, as a physical wheel
  query-cost          matchMedia('(color: 8)') and navigator.hardwareConcurrency
                      cost about what matchMedia('(min-width: 1px)') and
                      navigator.userAgent do (no sync IPC per read)
  timezone-cost       with a launch-level timezone, local Date getters cost
                      about what UTC getters do
  timezone-relaunch   a persistent profile relaunched with another timezone
                      reports the new one, in the page and in a worker
  web-serial          navigator.serial exists on a secure page. Any enterprise
                      policy turns Web Serial off unless DefaultSerialGuardSetting
                      turns it back on

    python tests/patches/stock-parity-probes.py
"""

import http.server
import json
import socket
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

FRAME = b"""<!doctype html><script>
document.hasStorageAccess().then(v => parent.postMessage({hasStorageAccess: v}, '*'));
</script>"""
PAGE = b"""<!doctype html><body style="height:5000px"><script>
const wheel = [];
addEventListener('wheel', e => {
  wheel.push({dy: e.deltaY, mode: e.deltaMode, wd: e.wheelDeltaY});
  document.body.dataset.wheel = JSON.stringify(wheel);
});
(async () => {
  let out;
  try { out = await (%PROBES%)(location.port); } catch (e) { out = {error: String(e)}; }
  document.body.dataset.result = JSON.stringify(out);
})();
</script></body>"""


def serve():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = FRAME if self.path.startswith("/frame") else PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


PROBES = """async (port) => {
  const out = {};
  out.secureContext = isSecureContext;
  out.serial = 'serial' in navigator;

  const c2d = document.createElement('canvas').getContext('2d');
  out.canvasFonts = {};
  for (const k of ['caption', 'icon', 'menu', 'message-box', 'small-caption', 'status-bar']) {
    c2d.font = '10px sans-serif';
    c2d.font = k;
    out.canvasFonts[k] = c2d.font;
  }

  const gl = document.createElement('canvas').getContext('webgl', {alpha: false, stencil: true, depth: false});
  if (gl) {
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    out.flipY = gl.getParameter(gl.UNPACK_FLIP_Y_WEBGL);
    out.alphaBits = gl.getParameter(gl.ALPHA_BITS);
    out.depthBits = gl.getParameter(gl.DEPTH_BITS);
    gl.getError();
    out.unmaskedNoExt = gl.getParameter(0x9246);
    out.unmaskedNoExtError = gl.getError();
  }
  const gl2 = document.createElement('canvas').getContext('webgl2');
  if (gl2) {
    gl2.hint(0x8B8B, gl2.NICEST);
    out.derivativeHint = gl2.getParameter(0x8B8B);
  }

  const pc = new RTCPeerConnection();
  const cands = [];
  pc.onicecandidate = e => { if (e.candidate) cands.push(e.candidate.candidate); };
  pc.createDataChannel('x');
  await pc.setLocalDescription();
  await new Promise(r => {
    const t = setTimeout(r, 6000);
    pc.addEventListener('icegatheringstatechange', () => { if (pc.iceGatheringState === 'complete') { clearTimeout(t); setTimeout(r, 300); } });
  });
  out.candidates = cands;
  out.statIds = [];
  (await pc.getStats()).forEach((v, k) => out.statIds.push(String(k)));
  pc.close();

  try {
    const r = await Promise.race([
      navigator.mediaDevices.getUserMedia({audio: true, fake: true}).then(s => { s.getTracks().forEach(t => t.stop()); return 'resolved'; }),
      new Promise(res => setTimeout(() => res('pending'), 3000)),
    ]);
    out.gumFake = r;
  } catch (e) {
    out.gumFake = 'rejected ' + e.name;
  }

  out.storageAccess = await new Promise(r => {
    addEventListener('message', e => r(e.data.hasStorageAccess), {once: true});
    const f = document.createElement('iframe');
    f.src = `http://127.0.0.1:${port}/frame`;
    document.body.appendChild(f);
    setTimeout(() => r('timeout'), 5000);
  });

  // The result of every read is accumulated into `sink`, and `sink` is returned.
  // Without that the JIT elides the whole loop for a side-effect-free getter --
  // which it did for navigator.userAgent on a CI runner, timing the BASELINE at
  // 0 ms and collapsing the comparison below into a flat 15 ms allowance.
  let sink = 0;
  const time = (fn) => {
    const t = performance.now();
    for (let i = 0; i < 20000; i++) sink += fn();
    return performance.now() - t;
  };
  // Each pair is timed ROUNDS times, interleaved, and compared by median. One
  // sample per getter let a single GC pause or CPU-steal spike on a shared
  // runner decide the verdict (hardwareConcurrency once took 77 ms against a
  // 50 ms allowance on a healthy build that passed the run before). The
  // regressions these catch cost extra on EVERY read, so they move every
  // sample and the median with them; a one-off spike moves one sample.
  const ROUNDS = 5;
  const median = (xs) => xs.slice().sort((a, b) => a - b)[xs.length >> 1];
  const pair = (a, b) => {
    const ta = [], tb = [];
    for (let r = 0; r < ROUNDS; r++) { ta.push(time(a)); tb.push(time(b)); }
    return [median(ta), median(tb)];
  };
  [out.costColor, out.costMinWidth] = pair(
    () => matchMedia('(color: 8)').matches ? 1 : 0,
    () => matchMedia('(min-width: 1px)').matches ? 1 : 0);
  [out.costHwc, out.costUA] = pair(
    () => navigator.hardwareConcurrency,
    () => navigator.userAgent.length);
  // Fresh Date objects: a Date caches its local-time fields after one read.
  let n = 0;
  [out.costLocalDate, out.costUTCDate] = pair(
    () => new Date(1.6e12 + (n++) * 3.6e6).getHours(),
    () => new Date(1.6e12 + (n++) * 3.6e6).getUTCHours());
  out.sink = sink;
  out.timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return out;
}"""


PAGE = PAGE.replace(b"%PROBES%", PROBES.encode())


def run_probes(binary, port):
    from camoufox.sync_api import Camoufox

    config = {"webrtc:ipv4": "203.0.113.7", "timezone": "Asia/Tokyo"}
    with Camoufox(headless=True, executable_path=str(binary), config=config, i_know_what_im_doing=True) as b:
        page = b.new_page()
        page.goto(f"http://localhost:{port}/")
        page.wait_for_function("() => document.body.dataset.result", timeout=60000)
        out = json.loads(page.evaluate("() => document.body.dataset.result"))
        if "error" in out:
            raise RuntimeError(out["error"])
        page.mouse.move(200, 200)
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(800)
        out["wheel"] = json.loads(page.evaluate("() => document.body.dataset.wheel || '[]'"))
        return out


def probe_wheel(binary, port, humanize):
    """One scroll of 300px, with humanize on or off.

    Off (the default) the caller's delta is delivered verbatim, which is what
    upstream's own suite asserts. On, the scroll is quantised into the notches a
    physical wheel produces. Both are shipped behaviour, so both are checked.
    """
    from camoufox.sync_api import Camoufox

    with Camoufox(headless=True, executable_path=str(binary), humanize=humanize,
                  i_know_what_im_doing=True) as b:
        page = b.new_page()
        page.goto(f"http://localhost:{port}/")
        page.mouse.move(200, 200)
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(1500)
        return json.loads(page.evaluate("() => document.body.dataset.wheel || '[]'"))


def relaunch_timezones(binary, port):
    from camoufox.sync_api import Camoufox

    seen = []
    with tempfile.TemporaryDirectory(prefix="parity-profile-") as profile:
        for tz in ("Asia/Tokyo", "America/Chicago"):
            with Camoufox(headless=True, executable_path=str(binary), persistent_context=True,
                          user_data_dir=profile, config={"timezone": tz}, i_know_what_im_doing=True) as ctx:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(f"http://localhost:{port}/")
                # A worker reads the per-context store, where a stale value surfaced.
                seen.append(page.evaluate("""async () => {
                  const w = new Worker(URL.createObjectURL(new Blob(
                    ["postMessage(Intl.DateTimeFormat().resolvedOptions().timeZone)"],
                    {type: 'text/javascript'})));
                  const worker = await new Promise(r => { w.onmessage = e => r(e.data); setTimeout(() => r('timeout'), 5000); });
                  return [Intl.DateTimeFormat().resolvedOptions().timeZone, worker];
                }"""))
                # prefs.js is written asynchronously; give a persisted value time to land.
                page.wait_for_timeout(3000)
    return seen


def main() -> int:
    binary = resolve_binary()
    server, port = serve()
    try:
        out = run_probes(binary, port)
        out["wheelHumanized"] = probe_wheel(binary, port, humanize=True)
        relaunch = relaunch_timezones(binary, port)
    finally:
        server.shutdown()
    print(json.dumps({**out, "relaunch": relaunch}, indent=1, default=str))

    failures = []
    for k, v in out["canvasFonts"].items():
        if v != k:
            failures.append(f"canvas-system-font: ctx.font = '{k}' read back {v!r}")
    if "flipY" in out:
        if out["flipY"] is not True:
            failures.append(f"webgl-state: UNPACK_FLIP_Y_WEBGL after pixelStorei(true) = {out['flipY']}")
        if out["alphaBits"] != 0:
            failures.append(f"webgl-state: ALPHA_BITS on an {{alpha: false}} context = {out['alphaBits']}")
        if out["unmaskedNoExt"] is not None or out["unmaskedNoExtError"] != 0x0500:
            failures.append(f"webgl-state: UNMASKED_RENDERER_WEBGL without the extension = "
                            f"{out['unmaskedNoExt']!r}, error {out['unmaskedNoExtError']}")
    else:
        print("note: no WebGL context on this host; webgl-state not checked")
    if "derivativeHint" in out and out["derivativeHint"] != 0x1102:
        failures.append(f"webgl-state: FRAGMENT_SHADER_DERIVATIVE_HINT after hint(NICEST) = {out['derivativeHint']}")
    if not out["candidates"]:
        failures.append("webrtc-no-servers: no candidates at all -- check is vacuous")
    if any(" typ srflx " in c for c in out["candidates"]):
        failures.append(f"webrtc-no-servers: srflx gathered with no iceServers: {out['candidates']}")
    if any("camou" in i for i in out["statIds"]):
        failures.append(f"webrtc-no-servers: getStats id names camoufox: {out['statIds']}")
    if out["gumFake"] != "resolved":
        failures.append(f"gum-fake: getUserMedia({{fake: true}}) {out['gumFake']}")
    if out["storageAccess"] is not False:
        failures.append(f"storage-partition: cross-site iframe hasStorageAccess() = {out['storageAccess']}")
    wheel = out["wheel"]
    # Default: the delta the caller asked for, in pixels, as one event.
    if len(wheel) != 1 or wheel[0]["mode"] != 0 or wheel[0]["dy"] != 300:
        failures.append(f"wheel-default: wheel(0, 300) gave {wheel}")
    # humanize=True: notches, each carrying one native tick.
    humanized = out["wheelHumanized"]
    if len(humanized) != 3 or any(e["wd"] % 120 for e in humanized):
        failures.append(f"wheel-notches: humanized wheel(0, 300) gave {humanized}")
    # 20000 reads of a value that lives in the config cost ~20 ms here, i.e.
    # ~1 us each: a hash lookup, no IPC. The state this guards against is a sync
    # IPC per read, measured at ~12 us each when it regressed -- 240 ms over the
    # same loop. The allowance sits an order of magnitude below that and well
    # above a healthy read, so neither a fast runner nor a slow one flips it.
    if out["costColor"] > 5 * out["costMinWidth"] + 40:
        failures.append(f"query-cost: (color) {out['costColor']:.0f} ms vs (min-width) {out['costMinWidth']:.0f} ms")
    if out["costHwc"] > 5 * out["costUA"] + 40:
        failures.append(f"query-cost: hardwareConcurrency {out['costHwc']:.0f} ms vs userAgent {out['costUA']:.0f} ms")
    if out["timeZone"] != "Asia/Tokyo":
        failures.append(f"timezone: launch-level zone not applied ({out['timeZone']}) -- timezone-cost is vacuous")
    # Not widened like the two above: a healthy local-Date loop costs ~2 ms here
    # against ~1 ms for UTC, and the regression this catches (DateTimeInfo
    # rebuilt per call under a launch timezone) ran ~1 us per call, i.e. ~20 ms
    # over this loop. A 40 ms allowance would step straight over it.
    if out["costLocalDate"] > 5 * out["costUTCDate"] + 15:
        failures.append(f"timezone-cost: getHours {out['costLocalDate']:.0f} ms vs getUTCHours {out['costUTCDate']:.0f} ms")
    if relaunch != [["Asia/Tokyo"] * 2, ["America/Chicago"] * 2]:
        failures.append(f"timezone-relaunch: persistent profile reported {relaunch}")
    if not out["secureContext"]:
        failures.append("web-serial: the probe page is not a secure context -- check is vacuous")
    elif not out["serial"]:
        failures.append("web-serial: navigator.serial is missing (policies.json needs DefaultSerialGuardSetting: 3)")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: page-observable behaviour matches stock Firefox on every probe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
