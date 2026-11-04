"""A fresh profile downloads the tracking-protection lists, as stock Firefox does.

Stock Firefox's Enhanced Tracking Protection (standard) blocks known
fingerprinting and cryptomining scripts by checking each load against the
URL-classifier tables, which it fetches from Remote Settings
(`tracking-protection-lists`) within seconds of startup. Without the tables
nothing is blocked, so a page sees a fingerprinting script load that stock
Firefox would have refused.

This guard needs the internet: the tables come only from Mozilla's servers.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import Marionette, free_port, marionette_args, resolve_binary

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
        (Path(tmp) / "user.js").write_text(f'user_pref("marionette.port", {port});\n', encoding="utf-8")
        with tempfile.TemporaryFile(mode="w+") as log:
            proc = subprocess.Popen(
                [str(binary), "--headless", "--no-remote", "--profile", tmp,
                 *marionette_args(), "about:blank"],
                stdout=log, stderr=subprocess.STDOUT,
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
    if result["skipRemote"]:
        failures.append("Remote Settings skips all remote activity, so no list is ever fetched")
    missing = [t for t in TABLES if t not in result["tables"]]
    if missing:
        failures.append(f"no {', '.join(missing)} after 60 s")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        print(output)
        return 1
    print("PASS: the fingerprinting and cryptomining lists reach a fresh profile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
