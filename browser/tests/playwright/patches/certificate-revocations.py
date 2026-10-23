"""Bundled OneCRL revocations must reach a fresh profile without a network fetch.

camoufox.cfg turns Remote Settings off, so the dump that
remote-security-settings.patch imports at startup is the only source. The
eMudhra issuer and serials are from Mozilla's test_onecrl_loads_bundle.js.
Check certificate storage itself: a completed load notification does not prove
that a revoked certificate will be rejected.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import Marionette, free_port, marionette_args, resolve_binary


PROBE = """
const storage = Cc["@mozilla.org/security/certstorage;1"].getService(Ci.nsICertStorage);
const issuer = Array.from(atob(
  "MFYxCzAJBgNVBAYTAklOMSUwIwYDVQQKDBxlTXVkaHJhIFRlY2hub2xvZ2llcyBMaW1pdGVkMSAwHgYDVQQDDBdlbVNpZ24gUm9vdCBUTFMgQ0EgLSBHMw=="
), c => c.charCodeAt(0));
const serials = [
  "00a4aee678f23362b4c0e460b772f214", "6cada367fb1c100088120ea202d568",
  "00c7c41efe92d825f05eae841a4a82c1", "588b2e3c2bb8cda13e1a1209254321",
  "296926c227a3a1526392b19482a504", "008009928a64107601af05fa2f19f109",
];
const done = arguments[arguments.length - 1];
const deadline = Date.now() + 10000;
function check() {
  const revoked = serials.map(serial => storage.getRevocationState(
    issuer, serial.match(/../g).map(byte => parseInt(byte, 16)), [], []
  ) === Ci.nsICertStorage.STATE_ENFORCE);
  if (!revoked.every(Boolean) && Date.now() < deadline) {
    setTimeout(check, 50);
    return;
  }
  done({
    revoked,
    controlNotRevoked: storage.getRevocationState(issuer, [1], [], [])
      === Ci.nsICertStorage.STATE_UNSET,
  });
}
check();
"""


def main() -> int:
    binary = resolve_binary()
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="camoufox-onecrl-") as tmp:
        profile = Path(tmp)
        # All external connections hit a closed local port, so nothing can
        # reach certificate storage except the bundled list.
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {port});\n'
            'user_pref("network.proxy.type", 1);\n'
            'user_pref("network.proxy.http", "127.0.0.1");\n'
            'user_pref("network.proxy.http_port", 9);\n'
            'user_pref("network.proxy.ssl", "127.0.0.1");\n'
            'user_pref("network.proxy.ssl_port", 9);\n'
            'user_pref("network.proxy.no_proxies_on", "");\n',
            encoding="utf-8",
        )
        with tempfile.TemporaryFile(mode="w+") as log:
            proc = subprocess.Popen(
                [str(binary), "--headless", "--no-remote", "--profile", tmp,
                 *marionette_args(), "about:blank"],
                stdout=log, stderr=subprocess.STDOUT,
            )
            client = None
            try:
                client = Marionette(port)
                result = client.call("WebDriver:ExecuteAsyncScript", {
                    "script": PROBE, "args": [], "scriptTimeout": 20000,
                })["value"]
            finally:
                if client:
                    client.close()
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                log.seek(0)
                output = log.read()

    print(result)
    failures = []
    if not all(result["revoked"]):
        failures.append("eMudhra revocations missing from fresh-profile certificate storage")
    if not result["controlNotRevoked"]:
        failures.append("unlisted control serial was revoked")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        print(output)
        return 1
    print("PASS: bundled revocations are enforced without network access.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
