"""
Verify C++ local-time formatting follows the claimed zone.

document.lastModified and XSLT date:date-time() format an instant as local
wall-clock time in C++, outside JS Date. timezone-spoofing.patch formats them
through ICU in the zone the context claims, with the offset ICU has for that
instant, never the host's zone or `TZ`.

Checked, with `TZ` set to a zone that is neither claimed nor UTC so that a read
of the host zone is visible:
  * document.lastModified of a loaded page (Last-Modified header) and of an
    XMLHttpRequest document, at fixed instants on both sides of a DST change,
    for Asia/Kolkata, Australia/Adelaide and America/New_York; the expected
    strings come from Python's zoneinfo
  * the lastModified of a DOMParser document (the current time) and the offset
    of XSLT date:date-time() agree with JS Date in the claimed zone
  * no claimed zone: the host zone, as stock
  * RFP's JSDateTimeUTC: UTC, as stock
  * a zone ICU cannot load crashes the content process, never answers in the
    host zone

Run from any venv that has playwright:
    python browser/tests/playwright/patches/timezone-local-time.py
    python browser/tests/playwright/patches/timezone-local-time.py --binary /path/to/camoufox-bin

Which binary is tested, in order of precedence:
    --binary <path> | $CAMOUFOX_EXECUTABLE_PATH | $CAMOUFOX_BINARY | the in-tree build
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

ORIGIN = "https://camoufox.test/"
HOST_ZONE = "Pacific/Auckland"  # the host's zone for these runs: never a claim below
STYLESHEET = """<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:date="http://exslt.org/dates-and-times"><xsl:output method="text"/>
  <xsl:template match="/"><xsl:value-of select="date:date-time()"/></xsl:template></xsl:stylesheet>"""

# (zone, UTC instant): both sides of each zone's DST change in 2026.
INSTANTS = [
    ("Asia/Kolkata", datetime(2026, 3, 10, 7, 28, tzinfo=timezone.utc)),
    ("Australia/Adelaide", datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)),   # ACDT +10:30
    ("Australia/Adelaide", datetime(2026, 4, 5, 20, 0, tzinfo=timezone.utc)),   # ACST +09:30
    ("America/New_York", datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)),     # EST
    ("America/New_York", datetime(2026, 3, 8, 8, 1, tzinfo=timezone.utc)),      # EDT
]

PAGE = """<!doctype html><script>
(async () => {
  const out = {lastModified: document.lastModified};
  const xhr = await new Promise(resolve => {
    const x = new XMLHttpRequest(); x.open('GET', '/doc.xml'); x.responseType = 'document';
    x.onload = () => resolve(x.response && x.response.lastModified); x.onerror = () => resolve(null); x.send();
  });
  out.xhrLastModified = xhr;
  const before = new Date();
  out.parsedLastModified = new DOMParser().parseFromString('<p>x</p>', 'text/html').lastModified;
  const sheet = new DOMParser().parseFromString(%(sheet)s, 'application/xml');
  const proc = new XSLTProcessor(); proc.importStylesheet(sheet);
  out.xslt = proc.transformToDocument(new DOMParser().parseFromString('<a/>', 'application/xml')).documentElement.textContent;
  const after = new Date();
  const pad = n => String(n).padStart(2, '0');
  const wall = d => `${pad(d.getMonth() + 1)}/${pad(d.getDate())}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  out.dateWalls = [wall(before), wall(after)];
  out.dateOffset = -after.getTimezoneOffset();
  document.documentElement.dataset.probe = JSON.stringify(out);
})();
</script>""" % {"sheet": json.dumps(STYLESHEET)}


async def probe(binary: Path, zone: Optional[str], instant: datetime,
                prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from playwright.async_api import async_playwright

    config: Dict[str, Any] = {"navigator.platform": "Win32"}
    if zone is not None:
        config["timezone"] = zone
    env = {**os.environ, "TZ": HOST_ZONE, "CAMOU_CONFIG_1": json.dumps(config)}
    last_modified = format_datetime(instant, usegmt=True)
    async with async_playwright() as p:
        browser = await p.firefox.launch(executable_path=str(binary), headless=True, env=env,
                                         firefox_user_prefs=prefs or {})
        try:
            page = await browser.new_page()
            crashed: List[bool] = []
            page.on("crash", lambda _: crashed.append(True))

            async def serve(route: Any) -> None:
                headers = {"Last-Modified": last_modified}
                if route.request.url.endswith("/doc.xml"):
                    await route.fulfill(content_type="application/xml", headers=headers, body="<a/>")
                else:
                    await route.fulfill(content_type="text/html", headers=headers, body=PAGE)

            await page.route(ORIGIN + "**", serve)
            try:
                await page.goto(ORIGIN)
                handle = await page.wait_for_function("() => document.documentElement.dataset.probe", timeout=30000)
            except Exception:
                return {"crashed": True}
            return json.loads(await handle.json_value())
        finally:
            await browser.close()


def expected_string(instant: datetime, zone: str) -> str:
    return instant.astimezone(ZoneInfo(zone)).strftime("%m/%d/%Y %H:%M:%S")


def expected_offset(zone: str, at: datetime) -> str:
    minutes = int(at.astimezone(ZoneInfo(zone)).utcoffset().total_seconds() // 60)
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def check(failures: List[str], label: str, got: Any, want: Any) -> None:
    ok = got == want
    print(f"    [{'ok  ' if ok else 'FAIL'}] {label}: {got}" + ("" if ok else f" (expected {want})"))
    if not ok:
        failures.append(label)


def check_live(failures: List[str], label: str, got: Dict[str, Any], zone: str) -> None:
    """The current-time reads agree with JS Date in the same zone."""
    now = datetime.now(timezone.utc)
    parsed = got["parsedLastModified"]
    check(failures, f"{label} DOMParser lastModified is a wall clock of that minute",
          parsed[:16] in got["dateWalls"], True)
    check(failures, f"{label} XSLT date-time() offset", got["xslt"][-6:], expected_offset(zone, now))
    check(failures, f"{label} XSLT offset equals JS Date's", got["dateOffset"],
          int(now.astimezone(ZoneInfo(zone)).utcoffset().total_seconds() // 60))


async def main() -> int:
    binary = resolve_binary()
    print(f"Binary: {binary}")
    failures: List[str] = []
    other = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    for zone, instant in INSTANTS:
        print(f"\n=== {zone} at {instant.isoformat()} (host zone {HOST_ZONE}) ===")
        got = await probe(binary, zone, instant)
        want = expected_string(instant, zone)
        check(failures, "document.lastModified", got.get("lastModified"), want)
        check(failures, "XMLHttpRequest document lastModified", got.get("xhrLastModified"), want)
        if got.get("lastModified"):
            check_live(failures, zone, got, zone)

    print("\n=== no claimed zone: the host zone, as stock ===")
    got = await probe(binary, None, other)
    check(failures, "document.lastModified", got.get("lastModified"), expected_string(other, HOST_ZONE))
    check(failures, "XSLT offset", got["xslt"][-6:], expected_offset(HOST_ZONE, datetime.now(timezone.utc)))

    print("\n=== JSDateTimeUTC: UTC, as stock ===")
    prefs = {"privacy.fingerprintingProtection": True, "privacy.fingerprintingProtection.overrides": "+JSDateTimeUTC"}
    got = await probe(binary, "Asia/Kolkata", other, prefs)
    check(failures, "document.lastModified", got.get("lastModified"), expected_string(other, "UTC"))
    check(failures, "XSLT offset", got["xslt"][-6:], "+00:00")

    print("\n=== a zone ICU cannot load is loud ===")
    try:
        got = await probe(binary, "Mars/Olympus_Mons", other)
    except Exception as error:  # the browser may refuse to start at all: also loud
        print(f"    (launch failed: {str(error).splitlines()[0]})")
        got = {}
    check(failures, "the content process crashes, no probe result", got.get("lastModified"), None)

    print()
    if failures:
        print(f"FAIL: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("PASS: lastModified and XSLT date-time() follow the claimed zone at every instant.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
