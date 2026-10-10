"""
Verify a context's font and voice lists hold in every content process.

NewContext() hands each context its own font list and speech voices through
window setters (setFontList, setSpeechVoices). The first document to call a
setter marks it used for the whole context, in storage every process shares,
so later documents in the context never call it again. The lists themselves
were kept in a per-process static map, so a document of the same context that
landed in another content process found no list and showed the launch-level
fonts and voices instead.

The probe gives one context its own short lists through an init script, then
opens it on several loopback addresses. Each address is its own site, so the
pages spread across content processes, and each reports which of the
launch-level fonts and voices it can see.

What PASS means: every page of the context sees the same fonts and voices as
the first, and fewer than the launch level does.

    python browser/tests/playwright/patches/context-lists-across-processes.py
"""

import asyncio
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

CAMOUFOX = Path(__file__).resolve().parents[4] / "python" / "src" / "camoufox"

HOSTS = [f"127.0.0.{n}" for n in range(1, 9)]

PROBE = """async (fonts) => {
  // document.fonts.check() is true for any font that needs no download,
  // installed or not, so measure: a font is there if it changes the width of
  // the text against both fallbacks.
  const ctx = document.createElement('canvas').getContext('2d');
  const width = font => { ctx.font = font; return ctx.measureText('mmmmmmmmmmlli10OQ@#').width; };
  const base = ['monospace', 'serif'].map(g => [g, width(`72px ${g}`)]);
  const visible = fonts.filter(f => base.some(([g, w]) => width(`72px "${f}", ${g}`) !== w));
  let voices = speechSynthesis.getVoices();
  if (!voices.length)
    voices = await new Promise(r => {
      speechSynthesis.onvoiceschanged = () => r(speechSynthesis.getVoices());
      setTimeout(() => r(speechSynthesis.getVoices()), 2000);
    });
  return {fonts: visible, voices: voices.map(v => v.name).sort()};
}"""


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    candidates = json.loads((CAMOUFOX / "fonts.json").read_text())["win"]
    root = Path(__file__).resolve().parent / "assets"
    server = ThreadingHTTPServer(("0.0.0.0", 0), partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    # The launch level allows every candidate; the context narrows both lists.
    async with AsyncCamoufox(headless=True, os="windows", config={"fonts": candidates},
                             i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        launch_page = await browser.new_page()
        await launch_page.goto(f"http://{HOSTS[0]}:{port}/")
        launch = await launch_page.evaluate(PROBE, candidates)
        # The probe measures against monospace and serif, so the fonts those
        # resolve to on Windows must stay visible in the context too.
        fonts = sorted({*sorted(launch["fonts"])[:18], "Courier New", "Times New Roman"})
        voices = launch["voices"][:1]

        context = await browser.new_context()
        await context.add_init_script(
            f"if (typeof setFontList === 'function') setFontList({json.dumps(','.join(fonts))});"
            f"if (typeof setSpeechVoices === 'function') setSpeechVoices({json.dumps(','.join(voices))});"
        )
        seen = {}
        for host in HOSTS:
            page = await context.new_page()
            await page.goto(f"http://{host}:{port}/")
            seen[host] = await page.evaluate(PROBE, candidates)
    server.shutdown()

    if len(launch["voices"]) < 2:
        print(f"  FAIL: the launch level has {len(launch['voices'])} voices; narrowing needs two")
        return 1
    # The first page is the reference: it is where the lists were set, and a
    # listed font's aliases (Helvetica for Arial) show there as on Windows.
    passed = True
    first = seen[HOSTS[0]]
    for kind in ("fonts", "voices"):
        if len(first[kind]) >= len(launch[kind]):
            passed = False
            print(f"  FAIL {kind}: the context list did not apply on {HOSTS[0]} "
                  f"({len(first[kind])} of the launch-level {len(launch[kind])})")
        for host in HOSTS[1:]:
            if seen[host][kind] != first[kind]:
                passed = False
                extra = sorted(set(seen[host][kind]) - set(first[kind]))
                print(f"  FAIL {kind} on {host}: {len(seen[host][kind])} visible, "
                      f"{len(first[kind])} on {HOSTS[0]}; extra: {extra[:5]}")
    if passed:
        print(f"  PASS: {len(HOSTS)} sites all see the context's {len(first['fonts'])} fonts "
              f"and {len(first['voices'])} voice, of {len(launch['fonts'])} and "
              f"{len(launch['voices'])}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
