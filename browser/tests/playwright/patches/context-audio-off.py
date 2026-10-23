r"""
A context can turn its Web Audio noise off while the rest of the browser keeps it.

audio-fingerprint-manager.patch noises Web Audio output with a seed per
context, and a context without a seed of its own takes the launch's
audio:seed. A context's seed of 0 therefore meant "the launch's seed", not "no
noise", so on a browser launched with noise no context could render stock
audio. setAudioFingerprintNoise(false) says it: that context renders as stock
Firefox does, whatever the launch seed.

The reference is the output of a launch with the noise off (audio:seed 0). On a
second launch with the noise on, the context that called
setAudioFingerprintNoise(false) must match it, on its first document and after
a navigation (the setter is gone by then; the choice is not), while the page
in the default context and a NewContext() context with a seed of its own must
not.

What PASS means: the off context renders the reference output and the other
two do not.

    python browser/tests/playwright/patches/context-audio-off.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

# Rendered offline, so no audio device is needed. Read with copyFromChannel into
# an array of the probe's own: this runs in the isolated world, which may not
# read the page's typed arrays.
PROBE = """async () => {
  const ctx = new OfflineAudioContext(1, 5000, 44100);
  const osc = ctx.createOscillator();
  osc.type = 'triangle';
  osc.frequency.value = 10000;
  const comp = ctx.createDynamicsCompressor();
  osc.connect(comp);
  comp.connect(ctx.destination);
  osc.start(0);
  const data = new Float32Array(5000);
  (await ctx.startRendering()).copyFromChannel(data, 0);
  let sum = 0;
  for (let i = 4500; i < 5000; i++) sum += Math.abs(data[i]);
  return sum.toString();
}"""

TURN_OFF = "window.setAudioFingerprintNoise(false);"


def render(context) -> str:
    page = context.new_page()
    page.set_content("<p>x</p>")
    return page.evaluate(PROBE)


def main() -> int:
    from camoufox.sync_api import Camoufox, NewContext

    with Camoufox(**launch_kwargs(os="linux", i_know_what_im_doing=True,
                                  fingerprint_options={"audio": {"noise": False}})) as browser:
        stock = render(browser.new_context())
    print(f"  stock (launch noise off): {stock}")

    seen = {}
    with Camoufox(**launch_kwargs(os="linux", i_know_what_im_doing=True)) as browser:
        seen["default context"] = render(browser.new_context())
        off = browser.new_context()
        off.add_init_script(TURN_OFF)
        page = off.new_page()
        page.set_content("<p>x</p>")
        seen["off context"] = page.evaluate(PROBE)
        page.goto("about:blank")
        seen["off context, next document"] = page.evaluate(PROBE)
        seen["NewContext with its own seed"] = render(NewContext(browser))

    failures = []
    for name, value in seen.items():
        print(f"  {name}: {value}")
        stocked = value == stock
        if stocked != name.startswith("off context"):
            failures.append(f"{name} rendered {'stock' if stocked else 'noised'} audio")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: the off context renders stock audio; the page and another context stay noised.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
