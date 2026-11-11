r"""
A page computes what it computes on the claimed CPU: Intel, AMD or ARM64.

Skia's raster pipeline computes the non-separable and dodge/burn blend modes,
perspective and matrix inversion with RCPPS/RSQRTPS, whose bits differ between
Intel and AMD and agree across generations and OSes of one vendor
(docs/HOST-PARITY.md, browser/tests/cpu-estimates/). libopus's PVQ search (the
encoder) uses the same two instructions. Firefox's ARM64 build differs from
x86-64 in far more: every Web Audio node, canvas composite operation,
drawImage, filters and paths, Opus, VP8/VP9, relaxed SIMD wasm and the sign of
the default NaN. cpu-vendor-estimates.patch computes the claimed CPU's results
when general.cpu_identity names one (1 Intel, 2 AMD, 3 ARM64); the launcher
sets it from `cpu`.

This guard draws a gradient over a gradient with ten composite operations and
hashes getImageData (FNV-1a), launched with cpu={"manufacturer": "intel"} and
with "amd". Each must equal what stock Firefox gives on that vendor's CPU,
whatever the host's vendor. It then encodes one second of a fixed signal with
WebCodecs' AudioEncoder (Opus, 64 kbit/s, 20 ms frames) and hashes the encoded
bytes. Last, launched with cpu={"arch": "arm"}, it runs the CPU probe
(browser/tests/cpu-probe/page.html) and compares every key on which stock
Firefox's x86-64 and ARM64 Linux recordings differ with the ARM64 one, except
WebGL, which depends on the host, and canvas text, which depends on the drawn
devicePixelRatio.

Provenance of EXPECTED: stock Firefox 159.0, headless, a fresh profile, this
same probe page.
  intel: Core i9-11900H, Windows 11 26200.
  amd:   Ryzen 7 9850X3D, Ubuntu 26.04.
source-over, multiply, screen and soft-light use no estimate and agree on
both; the other six differ. Opus: the same hashes on an i7-12700H (Ubuntu)
and a Ryzen Threadripper 7970X (Firefox 158, Ubuntu). ARM64: the cpu-probe
results recorded on an Apple M4 and a Ryzen 9850X3D in the same Debian
container (browser/tests/cpu-probe/README.md).

What PASS means: each launch matches its CPU in every value. Without the
patch a launch naming another CPU gives the host's values and fails. The host
must be Intel or AMD x86-64 with a display whose GPU an ARM machine can have,
such as Xvfb's llvmpipe (LIBGL_ALWAYS_SOFTWARE=1 on a host with a GPU).

    python browser/tests/playwright/patches/cpu-vendor-estimates.py
"""

import json
import mimetypes
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

EXPECTED = {
    "intel": {
        "source-over": "5a333cc0", "multiply": "aa76dfd2", "screen": "8f139693",
        "soft-light": "705406a5", "color-dodge": "f563c640", "color-burn": "8a803ca5",
        "hue": "07ade2bc", "saturation": "a424da3f", "color": "b2e8412c",
        "luminosity": "250222dc", "opus": "74181f23/8518",
    },
    "amd": {
        "source-over": "5a333cc0", "multiply": "aa76dfd2", "screen": "8f139693",
        "soft-light": "705406a5", "color-dodge": "5c753f6c", "color-burn": "514ce277",
        "hue": "9e38d38f", "saturation": "3808efd2", "color": "d64ac5f7",
        "luminosity": "0b106bb9", "opus": "3edec3be/8518",
    },
}

PROBE = """() => {
  const W = 96, H = 64;
  const fnv = (d) => { let h = 0x811c9dc5; for (let i = 0; i < d.length; i++) { h ^= d[i]; h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(16).padStart(8, "0"); };
  const base = (ctx) => {
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "rgb(250,30,90)"); g.addColorStop(0.5, "rgb(40,200,120)"); g.addColorStop(1, "rgb(20,60,240)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  };
  const over = (ctx) => {
    const g = ctx.createLinearGradient(W, 0, 0, H);
    g.addColorStop(0, "rgba(255,220,0,0.8)"); g.addColorStop(1, "rgba(0,120,255,0.55)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  };
  const out = {};
  for (const op of ["source-over", "multiply", "screen", "color-dodge", "color-burn", "soft-light", "hue", "saturation", "color", "luminosity"]) {
    const c = document.createElement("canvas"); c.width = W; c.height = H;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    base(ctx); ctx.globalCompositeOperation = op; over(ctx);
    out[op] = fnv(ctx.getImageData(0, 0, W, H).data);
  }
  return out;
}"""

PAGE = "https://cpu-vendor-estimates.test/"
CPU_PROBE = Path(__file__).resolve().parents[2] / "cpu-probe"
STOCK_X86, STOCK_ARM64 = "linux-x86_64-docker-ryzen-9850x3d", "linux-arm64-docker-apple-m4"

OPUS_PROBE = """async () => {
  const fnv = (d) => { let h = 0x811c9dc5; for (let i = 0; i < d.length; i++) { h ^= d[i]; h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(16).padStart(8, "0"); };
  let seed = 777; const rnd = () => (seed = (Math.imul(seed, 1103515245) + 12345) >>> 0);
  const chunks = []; let err = null;
  const enc = new AudioEncoder({ output: (c) => { const b = new Uint8Array(c.byteLength); c.copyTo(b); chunks.push(...b); }, error: (e) => { err = e; } });
  enc.configure({ codec: "opus", sampleRate: 48000, numberOfChannels: 1, bitrate: 64000 });
  const n = 48000, s = new Float32Array(n); let ph = 0;
  for (let i = 0; i < n; i++) { ph = (ph + 37 + (i >> 9)) & 1023; const tri = (ph < 512 ? ph : 1023 - ph) - 256; s[i] = tri / 512 * 0.6 + ((rnd() >>> 20) - 2048) / 2048 * 0.05; }
  for (let off = 0; off < n; off += 960)
    enc.encode(new AudioData({ format: "f32", sampleRate: 48000, numberOfFrames: 960, numberOfChannels: 1, timestamp: off * 1e6 / 48000 | 0, data: s.subarray(off, off + 960) }));
  await enc.flush(); enc.close();
  return err ? "error: " + err : fnv(chunks) + "/" + chunks.length;
}"""


def host_vendor() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("vendor_id"):
                return {"GenuineIntel": "intel", "AuthenticAMD": "amd"}.get(line.split(":", 1)[1].strip(), "")
    except OSError:
        pass
    return ""


def render(**kwargs) -> dict:
    from camoufox.sync_api import Camoufox

    with Camoufox(**launch_kwargs(os="linux", **kwargs)) as browser:
        page = browser.new_page()
        # WebCodecs needs a secure context; about:blank is not one.
        page.route(PAGE, lambda route: route.fulfill(body="<p>x</p>", content_type="text/html"))
        page.goto(PAGE)
        out = page.evaluate(PROBE)
        out["opus"] = page.evaluate(OPUS_PROBE)
        return out


def stock(name: str) -> dict:
    return json.loads((CPU_PROBE / "results" / f"{name}.json").read_text())


def arm64_keys() -> dict:
    """The keys on which stock x86-64 and ARM64 Linux differ, with ARM64's values."""
    x86, arm = stock(STOCK_X86), stock(STOCK_ARM64)
    # Canvas text is rasterized at the drawn devicePixelRatio; the references are at 1.
    host_only = {"ua", "hc", "webgl", "canvas.text"}
    return {k: v for k, v in arm.items() if x86.get(k) != v and k not in host_only}


def probe(**kwargs) -> dict:
    """What browser/tests/cpu-probe/page.html POSTs, served from PAGE."""
    from camoufox.sync_api import Camoufox

    def serve(route):
        path = CPU_PROBE / route.request.url.removeprefix(PAGE).split("?")[0]
        if route.request.method == "POST":
            route.fulfill(status=204)
        elif path.is_file():
            route.fulfill(body=path.read_bytes(), content_type=mimetypes.guess_type(path)[0] or "text/plain")
        else:
            route.fulfill(status=404)

    with Camoufox(**launch_kwargs(os="linux", **kwargs)) as browser:
        page = browser.new_page()
        page.route(PAGE + "**", serve)
        with page.expect_request(lambda r: r.method == "POST", timeout=240_000) as posted:
            page.goto(PAGE + "page.html")
        return json.loads(posted.value.post_data)


def main() -> int:
    host = host_vendor()
    if platform.machine().lower() not in ("x86_64", "amd64") or not host:
        print(f"FAIL: needs an Intel or AMD x86-64 host, not {platform.machine()} {platform.processor()!r}")
        return 1

    seen = {v: render(cpu={"manufacturer": v}) for v in EXPECTED}
    failures = []
    for vendor, got in seen.items():
        wrong = sorted(k for k, v in EXPECTED[vendor].items() if got.get(k) != v)
        print(f"  cpu={vendor}: {'matches stock ' + vendor if not wrong else 'differs in ' + ', '.join(wrong)}")
        if wrong:
            failures.append(f"cpu={vendor}: {', '.join(f'{k} {got.get(k)} (stock {EXPECTED[vendor][k]})' for k in wrong)}")

    expected = arm64_keys()
    expected_errors = {k for k in stock(STOCK_ARM64) if k.endswith(".error")}
    # Headless, Firefox names a software renderer "GeForce GTX 980", which no ARM
    # machine has; under a display (Xvfb in CI) it reports llvmpipe.
    got = probe(cpu={"arch": "arm"}, headless=False)
    # A step that throws stops drawing from the page's shared random stream, so
    # every later key would differ for a reason that is not the CPU.
    errors = {k: v for k, v in got.items() if k.endswith(".error") and k not in expected_errors}
    if errors:
        print(f"FAIL: cpu=arm: the probe page failed: {errors}")
        return 1
    wrong = sorted(k for k, v in expected.items() if got.get(k) != v)
    print(f"  cpu=arm: {len(expected) - len(wrong)}/{len(expected)} values match stock ARM64")
    if wrong:
        failures.append(f"cpu=arm: {', '.join(f'{k} {got.get(k)} (stock {expected[k]})' for k in wrong)}")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: on this {host} host, a page computes as stock Firefox does on Intel, on AMD and on ARM64.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
