"""
Record humanize=True cursor movements from a real build and draw them as an
animated SVG: assets/humanize-cursor.svg, the figure in the README's "Page
Interactions" section.

Every point is a mousemove event the page received, at the time it received
it, so the figure shows what a site sees: the shape of each path, the spacing
of its events (close together = slow), and the pauses, replayed in real time.

    python3 scripts/cursor-demo.py /path/to/camoufox-bin
"""

import asyncio
import sys
from pathlib import Path

from camoufox.async_api import AsyncCamoufox

W, H = 900, 420
# A tour of short and long moves in several directions, like a user working
# through a form.
STOPS = [(80, 360), (820, 70), (460, 330), (170, 110), (640, 380), (840, 250), (80, 360)]
RECORDER = """
    window.moves = [];
    addEventListener("mousemove", e => moves.push([e.clientX, e.clientY, performance.now()]));
"""
OUT = Path(__file__).resolve().parent.parent / "assets" / "humanize-cursor.svg"
LABEL = 36  # caption strip under the page area
PAUSE_MS = 600  # between moves in the replay; the recorded gap is Playwright overhead


async def record(executable):
    moves = []
    async with AsyncCamoufox(
        headless=True, os="linux", humanize=True, executable_path=executable,
        window=(W + 100, H + 200),
    ) as browser:
        page = await browser.new_page()
        await page.set_content(f'<body style="margin:0;width:{W}px;height:{H}px"></body>')
        await page.mouse.move(*STOPS[0])
        for stop in STOPS[1:]:
            await page.evaluate(RECORDER)
            await page.mouse.move(*stop)
            moves.append(await page.evaluate("moves"))
    return moves


def render(moves):
    paths, frames, t0 = [], [], 0.0
    for events in moves:
        start = events[0][2]
        paths.append(events)
        for x, y, t in events:
            frames.append((x, y, t0 + t - start))
        t0 += events[-1][2] - start + PAUSE_MS
    total = t0
    keyTimes = ";".join(f"{t / total:.5f}" for *_, t in frames) + ";1"
    values = ";".join(f"{x},{y}" for x, y, _ in frames) + f";{frames[-1][0]},{frames[-1][1]}"

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H + LABEL}" width="{W}" height="{H + LABEL}"'
        ' font-family="ui-sans-serif,system-ui,sans-serif">',
        f'<rect width="{W}" height="{H + LABEL}" rx="12" fill="#0d1117"/>',
    ]
    for events in paths:
        pts = " ".join(f"{x},{y}" for x, y, _ in events)
        out.append(f'<polyline points="{pts}" fill="none" stroke="#3b82f6" stroke-opacity=".45" stroke-width="1.5"/>')
        out += [f'<circle cx="{x}" cy="{y}" r="1.6" fill="#93c5fd"/>' for x, y, _ in events]
    for x, y in STOPS[:-1]:
        out.append(f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="#f59e0b" stroke-width="2"/>')
    out.append(
        '<path d="M0,0 L0,17 L4.5,12.5 L7.5,19 L10,18 L7,11.5 L13,11.5 Z" fill="#fff" stroke="#000" stroke-width="1"'
        f' transform="translate({STOPS[0][0]},{STOPS[0][1]})">'
        f'<animateTransform attributeName="transform" type="translate" dur="{total / 1000:.3f}s"'
        f' repeatCount="indefinite" calcMode="linear" keyTimes="0;{keyTimes}" values="{STOPS[0][0]},{STOPS[0][1]};{values}"/>'
        "</path>"
    )
    n = sum(len(e) for e in moves)
    out.append(
        f'<text x="16" y="{H + LABEL - 14}" fill="#8b949e" font-size="13">{n} mousemove events from'
        f" {len(moves)} page.mouse.move() calls, humanize=True, replayed at recorded speed</text>"
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(asyncio.run(record(sys.argv[1]))))
    print(OUT)
