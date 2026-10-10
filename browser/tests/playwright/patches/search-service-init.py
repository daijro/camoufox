r"""
Verify the search service still initializes (no-search-engines.patch).

Camoufox ships no search engines: no-search-engines.patch short-circuits
SearchEngineSelector.#getConfiguration() with a hardcoded stub instead of
fetching from Remote Settings, which is dead anyway because camoufox.cfg sets
services.settings.server to "".

The stub's *shape* is load-bearing, and that is what this guards. The selector
is the Rust SearchEngineSelector, which deserializes search-config **v2**:

    #[serde(tag = "recordType", rename_all = "camelCase")]
    enum JSONSearchConfigurationRecords { ... }

`recordType` is the enum's tag, so a record without it aborts the entire
document with `missing field \`recordType\``. The stub used to be a v1 record
(`appliesTo`/`webExtension`), so setSearchConfig() threw on every single
launch, #init() died, and the browser ran with no search service at all --
which also takes out the urlbar's heuristic result, so history and autofill
never render. See daijro/camoufox#737.

That shipped broken in beta.28, .29 and .30 without anything noticing, because
the failure is a console error on a browser that otherwise starts fine. Hence
this test.

Note that "no engines" cannot be expressed as an empty configuration:
getEngineConfiguration() rejects `[]` with "Failed to get engine data from
Remote Settings", and SearchSettings refuses to write without an engine. So the
stub carries one inert engine, and this test asserts both halves -- that init
completes, AND that the only engine present is that inert one.

Run from any venv (no playwright needed -- this drives the binary directly):
    python browser/tests/playwright/patches/search-service-init.py
    python browser/tests/playwright/patches/search-service-init.py --binary /path/to/camoufox-bin
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import resolve_binary

# Long enough for the search service to init and write settings; the browser
# does not exit on its own with -headless about:blank, so it is killed after.
LAUNCH_TIMEOUT_S = 60

# Any of these appearing as an added engine means the "no search engines"
# stance has been lost.
REAL_ENGINES = ("Google", "Bing", "DuckDuckGo", "Perplexity", "Wikipedia",
                "Yahoo", "Ecosia", "Qwant", "Baidu", "Yandex")

ADDED_ENGINE_RE = re.compile(r'"#addEngineToStore: Adding engine:" "([^"]*)"')


def launch_and_capture(binary: Path, profile: Path) -> str:
    """Start the browser on a fresh profile with search logging, return output."""
    (profile / "user.js").write_text('user_pref("browser.search.log", true);\n')
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


def main() -> int:
    binary = resolve_binary()
    if not binary.exists():
        print(f"FATAL: no camoufox binary found (looked for {binary})")
        return 1

    print(f"Binary: {binary}")
    with tempfile.TemporaryDirectory(prefix="camoufox-search-") as tmp:
        profile = Path(tmp)
        log = launch_and_capture(binary, profile)
        settings_written = (profile / "search.json.mozlz4").exists()
        settings_blob = (
            (profile / "search.json.mozlz4").read_bytes() if settings_written else b""
        )

    failures = []

    # 1. The deserialization error this patch has historically caused.
    record_type_errors = log.count("missing field `recordType`")
    if record_type_errors:
        failures.append(
            f"the config stub failed to deserialize: {record_type_errors} "
            "'missing field `recordType`' error(s) -- the stub is not "
            "search-config v2 shaped"
        )

    # 2. init() has to actually finish.
    if "Completed #init" not in log:
        failures.append("SearchService never logged 'Completed #init'")
    for line in log.splitlines():
        if "#init: failure initializing search" in line:
            failures.append(f"SearchService reported init failure: {line.strip()[:160]}")
            break

    # 3. Settings must reach disk -- SearchSettings refuses to write with no engine.
    if not settings_written:
        failures.append("search.json.mozlz4 was never written")

    # 4. ...and the stance must still hold: nothing but the inert engine.
    engines = sorted(set(ADDED_ENGINE_RE.findall(log)))
    leaked = [e for e in engines if any(r.lower() in e.lower() for r in REAL_ENGINES)]
    if leaked:
        failures.append(f"real search engines were added: {', '.join(leaked)}")
    if not engines:
        failures.append("no engine was added at all (settings cannot be written)")

    print(f"  recordType errors      : {record_type_errors}")
    print(f"  'Completed #init'      : {'Completed #init' in log}")
    print(f"  search.json.mozlz4     : {'written' if settings_written else 'MISSING'}"
          f"{f' ({len(settings_blob)} bytes)' if settings_written else ''}")
    shown = ', '.join(f'"{e}"' for e in engines) if engines else "(none)"
    print(f"  engines added          : {shown}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: the search service initializes, and the only engine is the inert stub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
