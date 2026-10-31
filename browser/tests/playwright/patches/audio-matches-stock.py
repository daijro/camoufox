r"""
The build renders Web Audio exactly as stock Firefox does on this CPU.

Stock Firefox has one audio fingerprint per CPU architecture. The OS, the
sound card, the sample rate and the Firefox version do not move it, so a value
off those two is one no real machine produces (ci/tribal-rules.yml:
audio-is-not-noised). Camoufox used to noise the render with a seed per
identity (audio-fingerprint-manager.patch); that patch is gone.

Released libraries still send that seed: audio:seed in CAMOU_CONFIG at launch,
and window.setAudioFingerprintSeed() in each NewContext's init script. This
guard sends both, as they do, and checks that nothing moves the render:

  * the fingerprintjs render (sum of samples 4500..5000, and the SHA-256 of the
    whole buffer), the CreepJS AnalyserNode reads (getFloatFrequencyData and
    getFloatTimeDomainData), a biquad filter and a plain sine all equal the
    recorded stock values for this host's architecture;
  * in the default context, in a NewContext identity claiming another OS, in a
    context whose init script calls the old per-context setter, and in a
    second launch.

Provenance of EXPECTED: the 2026-10 audio study (audio-study/probe/probe.html,
the same graphs as PROBE below), 103 runs of stock Firefox 152-158.
  x86-64: 61 runs on AMD Ryzen 7 9850X3D, EPYC 7763/9V45/9V74, Intel i7-8700B,
          i9-11900H (Linux, macOS, Windows); the values are those of
          linux-ff158-default.
  arm64:  42 runs on Apple M1 (virtual), M4, M5 Ultra, Microsoft Cobalt
          100/200, Neoverse-N2 (macOS, Linux, Windows); the values are those of
          mac-m4-ff158-default.
Every run of an architecture gave the same values, to the bit.

What PASS means: every probe in every context and launch equals EXPECTED for
this architecture. On v158.0-beta.40 (noised) it fails.

    python browser/tests/playwright/patches/audio-matches-stock.py
"""

import platform
import sys
from pathlib import Path

import orjson

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

EXPECTED = {
    "x86_64": {
        "fpjs_sum": 35.749972093850374,
        "fpjs_sha": "dea0ebd6064236abd66b8f8bf7a3abf2074db125ead84ed42fcfce9466c13be4",
        "analyser_freq_sha": "7138c4b2b2ef186652377d768e612ff50cf7a85c101d999075ac17214e30c77a",
        "analyser_time_sha": "5de5da950f528d069a03b1637eba01b46c99d4bbf05dc8b37058437d327b20e7",
        "biquad_sum": 21012.13081460159,
        "biquad_sha": "2c227fe59bc7e92e7bca44e22c32ed87cc05f070871a33f3e14bf0cb2e849d08",
        "sine_sha": "b8c3978e7f5ea1c767066b9e7fda85ad011aa6e4e69de6aa0ca2f117c121102f",
    },
    "arm64": {
        "fpjs_sum": 35.74996626004577,
        "fpjs_sha": "8e127fb8b39c7e95dec34d0cefe176cd6585ac7fd5f851df6212db23c8a23aa7",
        "analyser_freq_sha": "8e8c19b492461bb902ad5098e52858f753cabca248ccf90cde5740188d071f2f",
        "analyser_time_sha": "2c2d59044cae47a80665a49cd50da10bc6eaa0ecb1b37120efc48e0334f83436",
        "biquad_sum": 21012.13078325092,
        "biquad_sha": "9fdc1dba7e3a7e10fe22bf1815a533fc69a3dd3ab1190dad8f898d24f3a2f207",
        "sine_sha": "b8c3978e7f5ea1c767066b9e7fda85ad011aa6e4e69de6aa0ca2f117c121102f",
    },
}
ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}

# What a released library sends: any non-zero seed noised the old build.
OLD_SEED = 424242
OLD_SETTER = f"window.setAudioFingerprintSeed && window.setAudioFingerprintSeed({OLD_SEED});"

# Rendered offline, so no audio device is needed. Every buffer is copied into an
# array of the probe's own (copyFromChannel, or the analyser filling it): this
# runs in the isolated world, which may not read the page's typed arrays.
PROBE = """async () => {
  const sha256 = (bytes) => {
    const K = new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
    const H = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
    const l = bytes.length, nb = ((l + 9 + 63) >> 6) << 6;
    const m = new Uint8Array(nb); m.set(bytes); m[l] = 0x80;
    const bits = l * 8; const dv = new DataView(m.buffer);
    dv.setUint32(nb - 4, bits >>> 0); dv.setUint32(nb - 8, Math.floor(bits / 4294967296));
    const W = new Uint32Array(64);
    const r = (x, n) => (x >>> n) | (x << (32 - n));
    for (let o = 0; o < nb; o += 64) {
      for (let i = 0; i < 16; i++) W[i] = dv.getUint32(o + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = r(W[i-15],7) ^ r(W[i-15],18) ^ (W[i-15] >>> 3);
        const s1 = r(W[i-2],17) ^ r(W[i-2],19) ^ (W[i-2] >>> 10);
        W[i] = (W[i-16] + s0 + W[i-7] + s1) >>> 0;
      }
      let [a,b,c,d,e,f,g,h] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (h + (r(e,6) ^ r(e,11) ^ r(e,25)) + ((e & f) ^ (~e & g)) + K[i] + W[i]) >>> 0;
        const t2 = ((r(a,2) ^ r(a,13) ^ r(a,22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0]+=a; H[1]+=b; H[2]+=c; H[3]+=d; H[4]+=e; H[5]+=f; H[6]+=g; H[7]+=h;
    }
    return Array.from(H, x => x.toString(16).padStart(8, "0")).join("");
  };
  const sha = (arr) => sha256(new Uint8Array(arr.buffer));
  const sumAbs = (arr, from = 0) => { let s = 0; for (let i = from; i < arr.length; i++) s += Math.abs(arr[i]); return s; };
  const samples = async (ctx, frames) => {
    const out = new Float32Array(frames);
    (await ctx.startRendering()).copyFromChannel(out, 0);
    return out;
  };
  const res = {};

  // fingerprintjs getUnstableAudioFingerprint
  let ctx = new OfflineAudioContext(1, 5000, 44100);
  let osc = ctx.createOscillator();
  osc.type = "triangle"; osc.frequency.value = 10000;
  const comp = ctx.createDynamicsCompressor();
  comp.threshold.value = -50; comp.knee.value = 40; comp.ratio.value = 12;
  comp.attack.value = 0; comp.release.value = 0.25;
  osc.connect(comp); comp.connect(ctx.destination); osc.start(0);
  let data = await samples(ctx, 5000);
  res.fpjs_sum = sumAbs(data, 4500);
  res.fpjs_sha = sha(data);

  // CreepJS: an AnalyserNode behind the compressor
  ctx = new OfflineAudioContext(1, 5000, 44100);
  const analyser = ctx.createAnalyser();
  osc = ctx.createOscillator();
  osc.type = "triangle"; osc.frequency.value = 10000;
  const dc = ctx.createDynamicsCompressor();
  dc.threshold.value = -50; dc.knee.value = 40; dc.attack.value = 0;
  osc.connect(dc); dc.connect(analyser); dc.connect(ctx.destination); osc.start(0);
  await ctx.startRendering();
  dc.disconnect(); osc.disconnect();
  const freq = new Float32Array(analyser.frequencyBinCount);
  analyser.getFloatFrequencyData(freq);
  const time = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(time);
  res.analyser_freq_sha = sha(freq);
  res.analyser_time_sha = sha(time);

  // a biquad lowpass on a sawtooth
  ctx = new OfflineAudioContext(1, 44100, 44100);
  osc = ctx.createOscillator(); osc.type = "sawtooth"; osc.frequency.value = 440;
  const f = ctx.createBiquadFilter(); f.type = "lowpass"; f.frequency.value = 1000; f.Q.value = 5;
  osc.connect(f); f.connect(ctx.destination); osc.start(0);
  data = await samples(ctx, 44100);
  res.biquad_sum = sumAbs(data);
  res.biquad_sha = sha(data);

  // a plain sine
  ctx = new OfflineAudioContext(1, 44100, 44100);
  osc = ctx.createOscillator(); osc.type = "sine"; osc.frequency.value = 1000;
  osc.connect(ctx.destination); osc.start(0);
  res.sine_sha = sha(await samples(ctx, 44100));
  return res;
}"""


def released_library_options() -> dict:
    """This library's launch options, plus the audio:seed a released one sends."""
    from camoufox.utils import get_env_vars, launch_options

    options = launch_options(**launch_kwargs(os="linux", i_know_what_im_doing=True))
    env = options["env"]
    chunks = sorted((int(k.rsplit("_", 1)[1]), k) for k in env if k.startswith("CAMOU_CONFIG_"))
    config = orjson.loads("".join(env.pop(k) for _, k in chunks))
    config["audio:seed"] = OLD_SEED
    # The binary under test's bundle, as launch_options passes it. Without a
    # path, get_env_vars finds its fontconfig in the installed release, and on
    # a runner with none it fetched one from the GitHub API (rate-limited, 403).
    binary = Path(options["executable_path"])
    env.update({k: v for k, v in get_env_vars(config, "lin", path=binary).items()
                if k.startswith("CAMOU_CONFIG_")})
    return options


def render(context) -> dict:
    page = context.new_page()
    page.set_content("<p>x</p>")
    return page.evaluate(PROBE)


def main() -> int:
    from camoufox.sync_api import Camoufox, NewContext

    arch = ARCH.get(platform.machine().lower())
    if arch is None:
        print(f"FAIL: no stock audio values recorded for {platform.machine()}")
        return 1
    expected = EXPECTED[arch]

    seen = {}
    with Camoufox(from_options=released_library_options()) as browser:
        seen["default context"] = render(browser.new_context())
        seen["NewContext claiming Windows"] = render(NewContext(browser, os="windows"))
        old = browser.new_context()
        old.add_init_script(OLD_SETTER)
        seen["context calling setAudioFingerprintSeed"] = render(old)
    with Camoufox(from_options=released_library_options()) as browser:
        seen["second launch"] = render(browser.new_context())

    failures = []
    for name, got in seen.items():
        wrong = {k: got.get(k) for k, v in expected.items() if got.get(k) != v}
        print(f"  {name}: fpjs {got.get('fpjs_sum')!r}, buffer {str(got.get('fpjs_sha'))[:12]}"
              f"{'' if not wrong else ', differs in ' + ', '.join(sorted(wrong))}")
        if wrong:
            failures.append(f"{name}: {wrong}")

    for failure in failures:
        print(f"FAIL: {failure} (stock {arch}: {expected})")
    if failures:
        return 1
    print(f"PASS: every context and launch renders stock {arch} audio, seed or no seed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
