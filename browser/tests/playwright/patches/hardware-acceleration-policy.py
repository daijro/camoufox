r"""
Verify hardware compositing is not disabled by policy.

settings/distribution/policies.json used to carry the enterprise policy
"HardwareAcceleration": false, which locks layers.acceleration.disabled=true.
Stock Firefox ships no policies, so every camoufox window ran software WebRender
with no hardware video decoding -- page-visible through
MediaCapabilities.decodingInfo(...).powerEfficient (false where stock is true),
the HDR probe and rendering behaviour, on every OS. The graphics decision log
read over Marionette showed "HW_COMPOSITING: Disabled by
layers.acceleration.disabled=true (FEATURE_FAILURE_COMP_PREF)".

This guard checks the shipped policy file, then launches the binary headed on a
private Xvfb display and reads, in chrome context: the active policies, the pref
(value and lock), and the HW_COMPOSITING decision log -- which must not name the
pref as the reason (Xvfb has no GPU, so compositing may be unavailable for other
reasons; only FEATURE_FAILURE_COMP_PREF means the policy is back).

    python browser/tests/playwright/patches/hardware-acceleration-policy.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, resolve_binary  # noqa: E402

BROWSER_ROOT = Path(__file__).resolve().parents[3]

JS = """
const gi = Cc["@mozilla.org/gfx/info;1"].getService(Ci.nsIGfxInfo);
const hw = (gi.getFeatureLog().features || []).find(f => f.name === "HW_COMPOSITING");
return {
  policies: Object.keys(Services.policies.getActivePolicies() || {}),
  locked: Services.prefs.prefIsLocked("layers.acceleration.disabled"),
  disabled: Services.prefs.getBoolPref("layers.acceleration.disabled", false),
  hwLog: hw ? hw.log.map(e => [e.type, e.status, e.message, e.failureId].join(" | ")) : [],
};
"""


def main() -> int:
    failures = []
    policies = json.loads((BROWSER_ROOT / "settings/distribution/policies.json").read_text())["policies"]
    if "HardwareAcceleration" in policies:
        failures.append(f"policies.json sets HardwareAcceleration={policies['HardwareAcceleration']!r}")

    binary = resolve_binary()
    port = free_port()
    with tempfile.TemporaryDirectory() as profile, hidden_display():
        Path(profile, "user.js").write_text(f'user_pref("marionette.port", {port});\n')
        proc = subprocess.Popen(
            [str(binary), "-no-remote", "-profile", profile, *marionette_args(), "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            m = Marionette(port)
            state = m.js(JS)
            m.close()
        finally:
            proc.kill()
            proc.wait()

    print(f"  active policies                      : {', '.join(sorted(state['policies'])) or '(none)'}")
    print(f"  layers.acceleration.disabled         : {state['disabled']} (locked: {state['locked']})")
    for entry in state["hwLog"]:
        print(f"  HW_COMPOSITING log                   : {entry}")
    if "HardwareAcceleration" in state["policies"]:
        failures.append("the running browser has the HardwareAcceleration policy active")
    if state["disabled"] or state["locked"]:
        failures.append("layers.acceleration.disabled is set or locked")
    if any("FEATURE_FAILURE_COMP_PREF" in e for e in state["hwLog"]):
        failures.append("hardware compositing is disabled by pref")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: no policy or pref disables hardware compositing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
