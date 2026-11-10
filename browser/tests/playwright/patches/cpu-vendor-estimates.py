r"""
A canvas and an Opus stream come out as they do on the claimed CPU vendor's
machine.

Skia's raster pipeline computes the non-separable and dodge/burn blend modes,
perspective and matrix inversion with RCPPS/RSQRTPS, whose bits differ between
Intel and AMD and agree across generations and OSes of one vendor
(docs/HOST-PARITY.md, browser/tests/cpu-estimates/). cpu-vendor-estimates.patch
reproduces the other vendor's instructions when gfx.skia.cpu_vendor_estimates
names it; the launcher sets the pref from cpu_vendor. libopus's PVQ search
(the encoder) uses the same two instructions, and Gecko hands it the same table
(media/libopus/include/opus_cpu_estimates.h).

This guard draws a gradient over a gradient with ten composite operations and
hashes getImageData (FNV-1a), launched with cpu_vendor="intel" and with
cpu_vendor="amd". Each must equal what stock Firefox gives on that vendor's
CPU, whatever the host's vendor. It then encodes one second of a fixed signal
with WebCodecs' AudioEncoder (Opus, 64 kbit/s, 20 ms frames) and hashes the
encoded bytes.

Provenance of EXPECTED: stock Firefox 159.0, headless, a fresh profile, this
same probe page.
  intel: Core i9-11900H, Windows 11 26200.
  amd:   Ryzen 7 9850X3D, Ubuntu 26.04.
source-over, multiply, screen and soft-light use no estimate and agree on
both; the other six differ. Opus: the same hashes on an i7-12700H (Ubuntu)
and a Ryzen Threadripper 7970X (Firefox 158, Ubuntu).

What PASS means: both launches match their vendor in every operation. Without
the patch the launch naming the other vendor gives the host's hashes and fails.
The host must be Intel or AMD x86-64.

    python browser/tests/playwright/patches/cpu-vendor-estimates.py
"""

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


def main() -> int:
    host = host_vendor()
    if platform.machine().lower() not in ("x86_64", "amd64") or not host:
        print(f"FAIL: needs an Intel or AMD x86-64 host, not {platform.machine()} {platform.processor()!r}")
        return 1

    seen = {f"cpu_vendor={v!r}": (v, render(cpu_vendor=v)) for v in EXPECTED}
    failures = []
    for name, (vendor, got) in seen.items():
        wrong = sorted(k for k, v in EXPECTED[vendor].items() if got.get(k) != v)
        print(f"  {name}: {'matches stock ' + vendor if not wrong else 'differs in ' + ', '.join(wrong)}")
        if wrong:
            failures.append(f"{name}: {', '.join(f'{k} {got.get(k)} (stock {EXPECTED[vendor][k]})' for k in wrong)}")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: on this {host} host, canvas and Opus come out as stock Firefox's do on Intel and on AMD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
