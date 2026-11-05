r"""
Verify the search service starts with stock Firefox's engines.

no-search-engines.patch replaced the search configuration with one inert
engine whose search URL was the loopback address, and policies.json made it
the default. Stock Firefox reads search-config-v2 from Remote Settings (with
the copy packaged in omni.ja until the first sync), so a fresh profile has
Google, Bing, DuckDuckGo, ... for its region, and fetches the collection and
its icons as stock does. The network sees that fetch, and a stock install
with no search engine is not one any user has.

This launches stock Firefox (--stock, else the release stock-gpu-parity
downloads) and Camoufox on fresh profiles with the region pinned, and checks
that the search service finishes initializing in both and adds the same
engines in the same order.

    python browser/tests/playwright/patches/search-service-init.py
    python browser/tests/playwright/patches/search-service-init.py --binary CAMOUFOX --stock FIREFOX
"""

import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import resolve_binary

HERE = Path(__file__).resolve().parent

# Long enough for the search service to init and write settings; the browser
# does not exit on its own with -headless about:blank, so it is killed after.
LAUNCH_TIMEOUT_S = 60

ADDED_ENGINE_RE = re.compile(r'"#addEngineToStore: Adding engine:" "([^"]*)"')


def launch_and_capture(binary: Path, profile: Path) -> str:
    """Start the browser on a fresh profile with search logging, return output."""
    # An official build keeps the chrome console off stdout, where the log is read.
    (profile / "user.js").write_text(
        'user_pref("browser.search.log", true);\n'
        'user_pref("devtools.console.stdout.chrome", true);\n'
        # The engines depend on the region, which Firefox otherwise detects
        # from the network partway through startup.
        'user_pref("browser.search.region", "US");\n'
    )
    proc = subprocess.Popen(
        [str(binary), "-profile", str(profile), "-headless", "-no-remote", "about:blank"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
    )
    try:
        out, _ = proc.communicate(timeout=LAUNCH_TIMEOUT_S)
        return out
    except subprocess.TimeoutExpired:
        # Expected: about:blank never exits. Take what was logged.
        proc.kill()
        out, _ = proc.communicate()
        return out


def stock_firefox() -> Path:
    spec = importlib.util.spec_from_file_location("getter_cost_parity", HERE / "getter-cost-parity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    binary = module.stock_firefox()
    module.prepare_stock(binary)
    return binary


def search_state(binary: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="search-") as tmp:
        profile = Path(tmp)
        log = launch_and_capture(binary, profile)
        written = (profile / "search.json.mozlz4").exists()
    failed = [line.strip()[:160] for line in log.splitlines()
              if "#init: failure initializing search" in line or "missing field `recordType`" in line]
    return {
        "completed": "Completed #init" in log,
        "failed": failed,
        "written": written,
        "engines": list(dict.fromkeys(ADDED_ENGINE_RE.findall(log))),
    }


def main() -> int:
    binary = resolve_binary()
    stock = stock_firefox()
    cf, ref = search_state(binary), search_state(stock)
    for name, state in (("stock", ref), ("camoufox", cf)):
        print(f"  {name:9} init {'completed' if state['completed'] else 'NOT completed'}, "
              f"settings {'written' if state['written'] else 'MISSING'}, engines: {state['engines']}")

    failures = []
    if not ref["completed"] or not ref["engines"]:
        failures.append("stock Firefox logged no search init with engines: the check proves nothing")
    if not cf["completed"]:
        failures.append("Camoufox's search service never logged 'Completed #init'")
    failures += [f"Camoufox: {line}" for line in cf["failed"]]
    if not cf["written"]:
        failures.append("Camoufox never wrote search.json.mozlz4")
    if cf["engines"] != ref["engines"]:
        failures.append(f"Camoufox added {cf['engines']}, stock {ref['engines']}")

    print()
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: the search service starts with stock's engines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
