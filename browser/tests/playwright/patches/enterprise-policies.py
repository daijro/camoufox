r"""
Verify Camoufox runs with no enterprise policies, as stock Firefox does.

settings/distribution/policies.json used to ship about twenty policies. Any
policy file, whatever it holds, puts Firefox in enterprise mode, and that
mode is visible from outside:

- DNS over HTTPS stands down. Its rollout heuristics trip on "enterprise
  policy present" (DoHHeuristics.sys.mjs enterprisePolicy()), so where stock
  Firefox in the US resolves through mozilla.cloudflare-dns.com, Camoufox sent
  plain DNS.
- "HardwareAcceleration": false locked layers.acceleration.disabled, so every
  window ran software WebRender with no hardware video decoding:
  MediaCapabilities.decodingInfo(...).powerEfficient was false where stock's
  is true.

What the policies did that Camoufox keeps is now a pref in camoufox.cfg
(updates, studies, the first-run page) or uBO's own default
(scripts/fetch-ubo.py freeze_lists). This guard checks that the install has
no policy file, then launches the binary headed on a private Xvfb display
and reads, in chrome context: the policy engine's status, the DoH
heuristic's enterprise check, the acceleration pref and the HW_COMPOSITING
decision log (Xvfb has no GPU, so compositing may be off for other reasons;
only FEATURE_FAILURE_COMP_PREF means a pref turned it off).

    python browser/tests/playwright/patches/enterprise-policies.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, resolve_binary  # noqa: E402


JS = """
return (async () => {
  const { Heuristics } = ChromeUtils.importESModule("moz-src:///toolkit/components/doh/DoHHeuristics.sys.mjs");
  const gi = Cc["@mozilla.org/gfx/info;1"].getService(Ci.nsIGfxInfo);
  const hw = (gi.getFeatureLog().features || []).find(f => f.name === "HW_COMPOSITING");
  return {
    policies: Object.keys(Services.policies.getActivePolicies() || {}),
    status: Services.policies.status,
    inactive: Services.policies.INACTIVE,
    dohPolicy: await Heuristics.checkEnterprisePolicy(),
    locked: Services.prefs.prefIsLocked("layers.acceleration.disabled"),
    disabled: Services.prefs.getBoolPref("layers.acceleration.disabled", false),
    hwLog: hw ? hw.log.map(e => [e.type, e.status, e.message, e.failureId].join(" | ")) : [],
  };
})();
"""


def main() -> int:
    failures = []
    binary = resolve_binary()
    for root in {binary.parent, binary.resolve().parent}:
        shipped = root / "distribution" / "policies.json"
        if shipped.exists():
            failures.append(f"the install ships {shipped}")
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
    print(f"  policy engine status                 : {state['status']} (inactive is {state['inactive']})")
    print(f"  DoH enterprise heuristic             : {state['dohPolicy']}")
    print(f"  layers.acceleration.disabled         : {state['disabled']} (locked: {state['locked']})")
    for entry in state["hwLog"]:
        print(f"  HW_COMPOSITING log                   : {entry}")
    if state["policies"]:
        failures.append(f"the running browser has policies active: {sorted(state['policies'])}")
    if state["status"] != state["inactive"]:
        failures.append(f"the policy engine is not inactive (status {state['status']})")
    if state["dohPolicy"] != "no_policy_set":
        failures.append(f"DNS over HTTPS stands down for an enterprise policy ({state['dohPolicy']})")
    if state["disabled"] or state["locked"]:
        failures.append("layers.acceleration.disabled is set or locked")
    if any("FEATURE_FAILURE_COMP_PREF" in e for e in state["hwLog"]):
        failures.append("hardware compositing is disabled by pref")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: no enterprise policies; DoH and hardware compositing are left to Firefox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
