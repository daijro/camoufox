"""
Verify the AnalyserNode frequency noise does not compound through smoothing.

audio-fingerprint-manager.patch scales each frequency bin by a fixed per-seed
multiplier. It used to scale the analyser's smoothed buffer in place, and
Firefox blends that buffer into every later analysis
(out = k * out + (1 - k) * |X|), so the multiplier fed back into itself: at the
default smoothing of 0.8 a 0.4% perturbation converged to about 2%, and kept
changing with how often the page read.

The probe needs no reference value. Two analysers on one tone, one with
smoothing 0 and one at 0.8 read until it converges, must agree, because both
apply the same multiplier to the same bins. They do in stock Firefox, where
there is no multiplier, and they do when the noise is applied to the copy
handed to the page.

What PASS means: the two analysers agree to within 0.01 dB on every bin above
the noise floor, for float and byte reads alike.

    python browser/tests/playwright/patches/audio-frequency-noise.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = """async () => {
  const ctx = new AudioContext();
  const osc = ctx.createOscillator();
  osc.frequency.value = 1000;
  const raw = ctx.createAnalyser();
  raw.smoothingTimeConstant = 0;
  const smoothed = ctx.createAnalyser();
  osc.connect(raw);
  osc.connect(smoothed);
  raw.connect(ctx.destination);
  smoothed.connect(ctx.destination);
  osc.start();
  await new Promise(r => setTimeout(r, 500));
  // One synchronous turn: both analysers see the same audio.
  const out = {state: ctx.state};
  const a = new Float32Array(raw.frequencyBinCount);
  const b = new Float32Array(smoothed.frequencyBinCount);
  for (let i = 0; i < 200; i++) smoothed.getFloatFrequencyData(b);
  raw.getFloatFrequencyData(a);
  let worst = 0, peak = -Infinity;
  for (let i = 0; i < a.length; i++) {
    peak = Math.max(peak, a[i]);
    if (a[i] > -100) worst = Math.max(worst, Math.abs(a[i] - b[i]));
  }
  out.floatDb = worst;
  out.peakDb = peak;
  const ab = new Uint8Array(raw.frequencyBinCount);
  const bb = new Uint8Array(smoothed.frequencyBinCount);
  for (let i = 0; i < 200; i++) smoothed.getByteFrequencyData(bb);
  raw.getByteFrequencyData(ab);
  let worstByte = 0;
  for (let i = 0; i < ab.length; i++) worstByte = Math.max(worstByte, Math.abs(ab[i] - bb[i]));
  out.byteSteps = worstByte;
  await ctx.close();
  return out;
}"""


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, os="linux", i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.set_content("<body style='height: 100vh'></body>")
        # Without a user activation the autoplay policy keeps the context suspended.
        await page.click("body")
        got = await page.evaluate(PROBE)

    if got["peakDb"] < -60:
        print(f"  FAIL: no tone reached the analysers (peak {got['peakDb']} dB, state {got['state']})")
        return 1
    passed = got["floatDb"] <= 0.01 and got["byteSteps"] <= 1
    verdict = "PASS" if passed else "FAIL"
    print(f"  {verdict}: smoothed vs unsmoothed analyser differ by {got['floatDb']:.4f} dB "
          f"(float) and {got['byteSteps']} steps (byte); limits 0.01 dB and 1 step")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
