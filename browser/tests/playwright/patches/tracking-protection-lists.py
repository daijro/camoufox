"""A fresh profile has the tracking-protection lists without touching the network.

Stock Firefox's Enhanced Tracking Protection (standard) blocks known
fingerprinting and cryptomining scripts by checking each load against the
URL-classifier tables. Without the tables nothing is blocked, so a page sees a
fingerprinting script load that stock Firefox would have refused. Camoufox
bundles them (scripts/remote_settings.py) so no request goes to Mozilla.

Every proxy pref points at a closed port here, so a table that shows up came
from the build.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import Marionette, free_port, marionette_args, marionette_env, resolve_binary

TABLES = ("base-fingerprinting-track-digest256", "base-cryptomining-track-digest256")

PROBE = """
const [tables, timeout] = arguments;
const done = arguments[arguments.length - 1];
const { Utils } = ChromeUtils.importESModule("resource://services-settings/Utils.sys.mjs");
const db = Cc["@mozilla.org/url-classifier/dbservice;1"].getService(Ci.nsIUrlClassifierDBService);
const deadline = Date.now() + timeout;
function check() {
  db.getTables(list => {
    const have = list.split("\\n").filter(Boolean).map(line => line.split(";")[0]);
    if (!tables.every(t => have.includes(t)) && Date.now() < deadline) {
      setTimeout(check, 500);
      return;
    }
    done({ skipRemote: Utils.shouldSkipRemoteActivity, server: Utils.SERVER_URL, tables: have });
  });
}
check();
"""


def main() -> int:
    binary = resolve_binary()
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="camoufox-etp-") as tmp:
        closed = free_port()
        prefs = {"marionette.port": port, "network.proxy.type": 1, "network.proxy.http": "127.0.0.1",
                 "network.proxy.http_port": closed, "network.proxy.ssl": "127.0.0.1",
                 "network.proxy.ssl_port": closed}
        (Path(tmp) / "user.js").write_text(
            "".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items()),
            encoding="utf-8")
        with tempfile.TemporaryFile(mode="w+") as log:
            proc = subprocess.Popen(
                [str(binary), "--headless", "--no-remote", "--profile", tmp,
                 *marionette_args(), "about:blank"],
                stdout=log, stderr=subprocess.STDOUT, env=marionette_env(),
            )
            client = None
            try:
                client = Marionette(port, timeout=120)
                client.call("WebDriver:SetTimeouts", {"script": 90000})
                result = client.call("WebDriver:ExecuteAsyncScript", {
                    "script": PROBE, "args": [list(TABLES), 60000],
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

    print(f"  Remote Settings server : {result['server']}")
    print(f"  remote activity skipped: {result['skipRemote']}")
    print(f"  classifier tables      : {len(result['tables'])}")
    failures = []
    if not result["skipRemote"]:
        failures.append("Remote Settings would poll Mozilla's servers")
    missing = [t for t in TABLES if t not in result["tables"]]
    if missing:
        failures.append(f"no {', '.join(missing)} after 60 s")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        print(output)
        return 1
    print("PASS: the fingerprinting and cryptomining lists load from the build alone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
