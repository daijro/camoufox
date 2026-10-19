"""
Verify reading navigator does not change a context's timezone.

navigator-spoofing.patch applied the launch-level `timezone` lazily, the first
time a page read navigator.platform or hardwareConcurrency. That ran after a
context's own timezone_id had been applied, so one navigator read moved the
page from the context's timezone to the launch-level one mid-script. The
launch-level timezone is applied once at startup in every process
(timezone-spoofing.patch); nothing else needs to apply it.

What PASS means: with a launch-level timezone of Asia/Tokyo and a context
timezone_id of America/New_York, the page reports New York before and after
reading navigator, on its first page and on a later one.

    python browser/tests/playwright/patches/timezone-stable.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = """() => {
  const zone = () => [Intl.DateTimeFormat().resolvedOptions().timeZone,
                      new Date(2026, 0, 1).getTimezoneOffset()];
  const before = zone();
  navigator.platform;
  navigator.hardwareConcurrency;
  return [before, zone()];
}"""

EXPECTED = [["America/New_York", 300], ["America/New_York", 300]]


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    passed = True
    async with AsyncCamoufox(headless=True, os="linux", config={"timezone": "Asia/Tokyo"},
                             i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        context = await browser.new_context(timezone_id="America/New_York")
        for label in ("first page", "second page"):
            page = await context.new_page()
            await page.goto("about:blank")
            got = await page.evaluate(PROBE)
            if got == EXPECTED:
                print(f"  PASS {label}: {got[1][0]} before and after reading navigator")
            else:
                passed = False
                print(f"  FAIL {label}: before {got[0]}, after reading navigator {got[1]}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
