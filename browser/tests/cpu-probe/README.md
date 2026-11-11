# CPU probe

What a page can compute that differs between CPUs, measured on stock Firefox.
`page.html` runs each test, hashes the result (FNV-1a) and POSTs the hashes;
`probe.py` serves it, launches a Firefox headless with a fresh profile and
prints the JSON. `compare.py` groups each key's values across result files.

    python3 -I probe.py <firefox binary> [pref=value ...] > result.json
    python3 compare.py results/*.json

Tests: Math functions (NaN results hashed as one value; NaN's bits are the
`nan` key), DOMMatrix, layout and SVG geometry with two webfonts, canvas (18
composite operations, gradients, paths, filter, drawImage, text), a WebGL
shader, WebAssembly relaxed SIMD (`relaxed.b64`), Web Audio nodes rendered
offline, and WebCodecs encoders.

The two webfonts come from Firefox's `layout/reftests/fonts`:
`DejaVuSansMono.woff` (Bitstream Vera license, DejaVu changes public domain)
and `VotoSerifGX.latin1.ttf` (SIL Open Font License 1.1). Each carries its
license in its `name` table.

`Dockerfile` (`--build-arg FFARCH=linux-x86_64` or `linux-aarch64`) runs the
same Firefox 159.0 on Linux for another architecture, with the same fonts, so
an ARM64 host's Linux values can be compared with x86-64's. WebGL is
unavailable in it.

## Results, stock Firefox 159.0 (`results/`)

| File | CPU | OS |
| --- | --- | --- |
| `linux-x86_64-i7-12700h` | Intel Core i7-12700H | Ubuntu |
| `windows-x86_64-i9-11900h` | Intel Core i9-11900H | Windows 11 26200 |
| `linux-x86_64-ryzen-9850x3d` | AMD Ryzen 7 9850X3D (Zen 5) | Ubuntu 26.04 |
| `linux-x86_64-threadripper-7970x-ff158` | AMD Threadripper 7970X (Zen 4) | Ubuntu, Firefox 158 (snap) |
| `linux-x86_64-docker-ryzen-9850x3d` | AMD Ryzen 7 9850X3D | Debian trixie container |
| `linux-arm64-docker-apple-m4` | Apple M4 | Debian trixie container (arm64) |
| `macos-arm64-apple-m4` | Apple M4 | macOS 27.0 |

What they show:

- Intel vs AMD: only the six estimate-based composite operations (`color`,
  `color-burn`, `color-dodge`, `hue`, `luminosity`, `saturation`) and the Opus
  encoder. Both are RCPPS/RSQRTPS, reproduced by `cpu-vendor-estimates.patch`
  (`docs/HOST-PARITY.md`).
- x86-64 vs ARM64 (same OS, same fonts, in the containers): every Web Audio
  node, every canvas composite operation, drawImage, filter and paths, Opus,
  VP9, 9 of 11 relaxed SIMD operations, and the sign of the default NaN.
  Layout, DOMMatrix, Math and text measurement agree. `cpu-vendor-estimates.patch`
  computes all of it on x86-64 when `general.cpu_identity` is 3; the guard
  `cpu-vendor-estimates` checks it against `linux-arm64-docker-apple-m4`.
- OS, not CPU: Windows differs in Math sin/cos/tan/pow, layout, DOMMatrix,
  text and Vorbis; macOS in pow, layout, DOMMatrix and text.
- Host-dependent rather than CPU-dependent: H.264 encoder availability,
  WebGL renderer and shader, hardwareConcurrency. The Firefox 158 run also
  differs in canvas paths and AV1.
