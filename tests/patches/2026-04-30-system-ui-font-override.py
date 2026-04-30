"""
Verify the system-ui font spoofing patch (system-ui-font-spoofing.patch).

The patch reads navigator.platform from MaskConfig and returns the appropriate
system font for GetSystemUIFontFamilies(): Helvetica for macOS, Segoe UI for
Windows. Without it, Linux spoofing macOS resolves system-ui to "Sans" via GTK.

Run from dvsa-bot to get the right venv:
    cd ~/20tech/drivingtest/dvsa-bot
    uv run python ~/20tech/oss/camoufox/tests/patches/2026-04-30-system-ui-font-override.py

What PASS means:
    Canvas measureText with unquoted "system-ui" produces the same width as
    the expected system font for the spoofed OS.

Caveat — CSS font syntax:
    "system-ui" UNQUOTED is a CSS generic keyword → ResolveGenericFontNames.
    "system-ui" QUOTED is a literal family name → FindAndAddFamiliesLocked.
    This test uses unquoted, which is what websites use and what the patch fixes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import launch_camoufox


EXPECTED_FONT = {
    "macos": "Helvetica",
    "windows": "Segoe UI",
}

MEASURE_TEXT_JS = """(() => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const testStr = 'mmmmmmmmmmlli';

    ctx.font = '72px monospace';
    const baseW = ctx.measureText(testStr).width;

    const results = {};

    // Unquoted generics — these go through ResolveGenericFontNames
    for (const name of ['system-ui', 'sans-serif']) {
        ctx.font = '72px ' + name + ', monospace';
        results[name] = ctx.measureText(testStr).width;
    }

    // Named fonts — direct lookup via FindAndAddFamiliesLocked
    for (const name of ['Helvetica', 'Segoe UI', 'Sans']) {
        ctx.font = '72px "' + name + '", monospace';
        results[name] = ctx.measureText(testStr).width;
    }

    return { widths: results, baseline: baseW };
})()"""


async def test_os(target_os: str) -> bool:
    expected_family = EXPECTED_FONT.get(target_os)
    if not expected_family:
        print(f"  SKIP: no expected system-ui font for {target_os}")
        return True

    async with launch_camoufox(os=target_os) as (page, config):
        platform = config.get("navigator.platform", "unknown")
        result = await page.evaluate(MEASURE_TEXT_JS)

    widths = result["widths"]
    baseline = result["baseline"]

    print(f"  navigator.platform: {platform}")
    print(f"  Expected system-ui: {expected_family}")
    print(f"  Baseline (mono):    {baseline}")
    for name, w in widths.items():
        tag = " (baseline)" if w == baseline else ""
        print(f"    {name:20s}  {w}{tag}")

    system_ui_w = widths["system-ui"]
    expected_w = widths.get(expected_family, None)

    if expected_w is None or expected_w == baseline:
        print(f"  SKIP: {expected_family} not available as a named font")
        return True

    if system_ui_w == expected_w:
        print(f"  PASS: system-ui resolves to {expected_family}")
        return True

    if system_ui_w == baseline:
        print(f"  FAIL: system-ui fell through to monospace baseline")
        return False

    sans_w = widths.get("Sans", baseline)
    if system_ui_w == sans_w and sans_w != expected_w:
        print(f"  FAIL: system-ui resolves to Sans (Linux leak)")
        return False

    print(f"  FAIL: system-ui width {system_ui_w} doesn't match {expected_family} ({expected_w})")
    return False


async def main() -> int:
    all_passed = True
    for target_os in ["macos", "windows"]:
        print(f"\n=== {target_os} ===")
        passed = await test_os(target_os)
        if not passed:
            all_passed = False

    print()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
