r"""
Verify Nimbus is disabled in a build without Normandy, so the new tab's
Activity Stream starts (nimbus-without-normandy.patch).

Stock starts Nimbus from Normandy. Camoufox builds Normandy out, so Nimbus
counted as enabled but never started; Activity Stream waits for it, never ran,
and every preloaded new tab's messages queued in AboutNewTabParent holding its
closed window (~7 MB a browser context). With nimbus.rollouts.enabled off
(camoufox.cfg) and Firefox Labs tied to MOZ_NORMANDY, ExperimentAPI.enabled is
false, which is what lets Nimbus report ready at once. No policy file is
involved (enterprise-policies.py).

Launches the binary headed on a private Xvfb display and reads ExperimentAPI
in chrome context.

    python browser/tests/playwright/patches/nimbus-without-normandy.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, marionette_env, resolve_binary  # noqa: E402


JS = """
const { ExperimentAPI } = ChromeUtils.importESModule("resource://nimbus/ExperimentAPI.sys.mjs");
const { AppConstants } = ChromeUtils.importESModule("resource://gre/modules/AppConstants.sys.mjs");
return {
  normandy: AppConstants.MOZ_NORMANDY,
  enabled: ExperimentAPI.enabled,
  labs: ExperimentAPI.labsEnabled,
  rollouts: ExperimentAPI.rolloutsEnabled,
  studies: ExperimentAPI.studiesEnabled,
  policies: Object.keys(Services.policies.getActivePolicies() || {}),
};
"""


def main() -> int:
    binary = resolve_binary()
    port = free_port()
    with tempfile.TemporaryDirectory() as profile, hidden_display():
        Path(profile, "user.js").write_text(f'user_pref("marionette.port", {port});\n')
        proc = subprocess.Popen(
            [str(binary), "-no-remote", "-profile", profile, *marionette_args(), "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=marionette_env(),
        )
        try:
            m = Marionette(port)
            state = m.js(JS)
            m.close()
        finally:
            proc.kill()
            proc.wait()

    for key in ("normandy", "enabled", "labs", "rollouts", "studies"):
        print(f"  {key:9}: {state[key]}")
    failures = []
    if state["normandy"]:
        print("FAIL: this build has Normandy, which Camoufox leaves out (MOZ_NORMANDY)")
        return 1
    for key in ("enabled", "labs", "rollouts", "studies"):
        if state[key]:
            failures.append(f"ExperimentAPI.{key} is true in a build without Normandy")
    if state["policies"]:
        failures.append(f"policies are active: {state['policies']}")
    for f in failures:
        print(f"FAIL: {f}")
    if not failures:
        print("PASS: Nimbus is disabled without a policy file")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
