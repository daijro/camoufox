"""
A click's person-paced rests hold up no other page.

Juggler dispatches input from every page on one process-wide chain, one slot at
a time. A click rests before its press and during its hold; rested inside the
slot, every other context's input waited for it, so parallel contexts clicked
one at a time (5.7 clicks a second from 8 contexts, where they reached 44 before
the rests). The rests now run on the page's own turn, so another page's input
reaches its page while this page's button is down.

    python browser/tests/playwright/patches/driven-click-throughput.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PAGES = 4
CLICKS = 8
PAGE = '<!doctype html><button id="b" style="width:120px;height:40px">b</button>'
RECORD = """() => {
  window.__ev = [];
  window.__clicks = window.__blurs = 0;
  const button = document.getElementById('b');
  for (const t of ['mousedown', 'mouseup'])
    button.addEventListener(t, () => window.__ev.push([t, Date.now()]));
  button.addEventListener('click', () => window.__clicks++);
  window.addEventListener('blur', () => window.__blurs++);
}"""


async def clicks(browser):
    context = await browser.new_context()
    page = await context.new_page()
    await page.set_content(PAGE)
    await page.evaluate(RECORD)
    for _ in range(CLICKS):
        await page.locator("#b").click()
    return await page.evaluate("[window.__ev, window.__clicks, window.__blurs]")


async def probe(binary):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True, os="linux") as browser:
        return await asyncio.gather(*(clicks(browser) for _ in range(PAGES)))


def main() -> int:
    results = asyncio.run(probe(resolve_binary()))
    per_page = [events for events, _, _ in results]
    if any(len(events) != 2 * CLICKS or count != CLICKS or blurs for events, count, blurs in results):
        print(f"FAIL: another page's input cost a page clicks or its focus: "
              f"{[(len(events), count, blurs) for events, count, blurs in results]}")
        return 1
    holds = [
        (events[i][1], events[i + 1][1], n)
        for n, events in enumerate(per_page)
        for i in range(0, len(events), 2)
    ]
    others = [(at, n) for n, events in enumerate(per_page) for _, at in events]
    overlapped = sum(
        any(other != n and down < at < up for at, other in others) for down, up, n in holds
    )
    # A held chain makes this exactly zero, whatever the machine's speed.
    if not overlapped:
        print(f"FAIL: no page's input arrived during another page's {len(holds)} holds")
        return 1
    print(f"PASS: {overlapped} of {len(holds)} holds had another page's input arrive during them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
