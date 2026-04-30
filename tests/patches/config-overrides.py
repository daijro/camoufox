"""
Verify that config_overrides={'fonts:spacing_seed': 0} disables font spacing perturbation.

The bug: there was no way to disable font spacing perturbation through the Python API.
generate_context_fingerprint() always generated a random non-zero seed, and the caller
couldn't override it because init_script was already rendered by the time config was
returned. config_overrides applies after config is built but before init_script is
rendered, giving callers a clean override point.

Run:
    cd ~/20tech/drivingtest/dvsa-bot
    uv run python ~/20tech/oss/camoufox/tests/patches/2026-04-30-font-spacing-seed-override.py
"""

import asyncio
import sys

from helpers import MAX_PRESET_ATTEMPTS


async def test():
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    test_string = "The quick brown fox jumps over the lazy dog"
    failures = []

    # --- Test 1: config_overrides disables font spacing perturbation ---
    print("=== Test 1: config_overrides={'fonts:spacing_seed': 0} ===")

    last_error = None
    for attempt in range(MAX_PRESET_ATTEMPTS):
        preset = get_random_preset(os="macos")
        fp = generate_context_fingerprint(
            preset=preset,
            config_overrides={"fonts:spacing_seed": 0},
        )

        if fp["config"]["fonts:spacing_seed"] != 0:
            failures.append(
                f"Config seed is {fp['config']['fonts:spacing_seed']}, expected 0"
            )
            break

        try:
            async with AsyncCamoufox(
                fingerprint_preset=fp["preset"],
                headless=True,
                os="macos",
            ) as browser:
                context = await browser.new_context(**fp["context_options"])
                await context.add_init_script(fp["init_script"])
                page = await context.new_page()
                await page.goto("about:blank")

                widths = await page.evaluate(
                    """(testStr) => {
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');
                    const results = [];
                    for (let i = 0; i < 5; i++) {
                        ctx.font = '16px Arial';
                        results.push(ctx.measureText(testStr).width);
                    }
                    return results;
                }""",
                    test_string,
                )

                unique = set(widths)
                if len(unique) == 1:
                    print(f"  Measurements stable (all {widths[0]}): PASS")
                else:
                    failures.append(f"Measurements unstable with seed=0: {widths}")
                    print(f"  Measurements vary: {widths}: FAIL")
                break
        except ValueError as e:
            if "WebGL" in str(e):
                last_error = e
                continue
            raise
    else:
        raise RuntimeError("Could not find a valid preset") from last_error

    # --- Test 2: without config_overrides, seed is non-zero ---
    print("\n=== Test 2: default (no overrides) gets non-zero seed ===")
    preset2 = get_random_preset(os="macos")
    fp2 = generate_context_fingerprint(preset=preset2)
    seed2 = fp2["config"]["fonts:spacing_seed"]
    if seed2 != 0:
        print(f"  Default seed is {seed2} (non-zero): PASS")
    else:
        failures.append("Default seed is 0 — should be random non-zero")
        print(f"  Default seed is 0: FAIL")

    # --- Test 3: init_script contains setFontSpacingSeed(0) when overridden ---
    print("\n=== Test 3: init_script emits setFontSpacingSeed(0) ===")
    preset3 = get_random_preset(os="macos")
    fp3 = generate_context_fingerprint(
        preset=preset3,
        config_overrides={"fonts:spacing_seed": 0},
    )
    if "setFontSpacingSeed(0)" in fp3["init_script"]:
        print("  init_script contains setFontSpacingSeed(0): PASS")
    elif "setFontSpacingSeed" not in fp3["init_script"]:
        print("  init_script omits setFontSpacingSeed entirely: PASS (acceptable)")
    else:
        import re

        match = re.search(r"setFontSpacingSeed\((\d+)\)", fp3["init_script"])
        val = match.group(1) if match else "?"
        failures.append(f"init_script has setFontSpacingSeed({val}), expected 0")
        print(f"  init_script has setFontSpacingSeed({val}): FAIL")

    # --- Test 4: other seeds are NOT affected by a font-only override ---
    print("\n=== Test 4: audio/canvas seeds unaffected by font override ===")
    preset4 = get_random_preset(os="macos")
    fp4 = generate_context_fingerprint(
        preset=preset4,
        config_overrides={"fonts:spacing_seed": 0},
    )
    audio = fp4["config"]["audio:seed"]
    canvas = fp4["config"]["canvas:seed"]
    if audio != 0 and canvas != 0:
        print(f"  audio:seed={audio}, canvas:seed={canvas} (both non-zero): PASS")
    else:
        failures.append(f"Other seeds affected: audio={audio}, canvas={canvas}")
        print(f"  audio={audio}, canvas={canvas}: FAIL")

    # --- Summary ---
    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED ({len(failures)} issues):")
        for f in failures:
            print(f"  - {f}")
        return 1
    else:
        print("ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
