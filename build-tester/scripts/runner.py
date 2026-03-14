"""
Playwright test runner — launches Camoufox, runs per-context and global profiles,
collects results, and returns the full result dict.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bundle import ensure_bundle
from certificate import (
    build_certificate_text,
    generate_certificate,
    print_certificate,
    print_profile_result,
)
from constants import BOLD, FIREFOX_WEBGL_PREFS, RED, RESET, TEST_TIMEZONES, WEBRTC_TEST_IP, grade_color
from grading import (
    adjust_cross_os_font_checks,
    compute_cross_profile,
    compute_grade,
    compute_match_results,
    count_all_checks,
)
from presets import (
    generate_presets,
    inject_timezone,
    inject_webrtc_ip,
    preset_to_profile_config,
)
from server import start_http_server
from wsl import get_windows_host_ip, is_elf_binary


# ─── Per-Context Phase ────────────────────────────────────────────────────────

async def run_per_context_phase(
    browser,
    per_context_entries: list,
    test_page_url: str,
    profile_results: list,
) -> None:
    # Phase 1: Create all contexts simultaneously
    open_contexts = []
    for entry in per_context_entries:
        preset = entry["preset"]
        profile = entry["profile"]
        try:
            ctx_opts = {}
            vp = preset["contextOptions"].get("viewport")
            ctx_opts["viewport"] = (
                {"width": min(vp["width"], 1920), "height": min(vp["height"], 1080)}
                if vp else {"width": 1920, "height": 1080}
            )
            if preset["contextOptions"].get("userAgent"):
                ctx_opts["user_agent"] = preset["contextOptions"]["userAgent"]
            if preset["contextOptions"].get("deviceScaleFactor"):
                ctx_opts["device_scale_factor"] = preset["contextOptions"]["deviceScaleFactor"]
            if preset["contextOptions"].get("locale"):
                ctx_opts["locale"] = preset["contextOptions"]["locale"]
            if preset["contextOptions"].get("timezoneId"):
                ctx_opts["timezone_id"] = preset["contextOptions"]["timezoneId"]

            context = await browser.new_context(**ctx_opts)
            await context.add_init_script(preset["initScript"])
            page = await context.new_page()
            open_contexts.append({"context": context, "page": page, "profile": profile})
        except Exception as e:
            pr = {"profile": profile, "results": None, "matchResults": [], "grade": "F", "passCount": 0, "totalChecks": 0, "error": str(e)}
            profile_results.append(pr)
            print_profile_result(pr)

    if not open_contexts:
        return

    # Phase 2: Navigate all pages concurrently
    print(f"  Navigating {len(open_contexts)} contexts to test page...")
    await asyncio.gather(
        *[ctx["page"].goto(test_page_url, wait_until="domcontentloaded", timeout=30000) for ctx in open_contexts],
        return_exceptions=True,
    )

    # Phase 3: Wait for all tests to complete
    print(f"  Waiting for all per-context tests to complete...")
    await asyncio.gather(
        *[ctx["page"].wait_for_function("!!window.__testComplete__", timeout=120000) for ctx in open_contexts],
        return_exceptions=True,
    )

    # Phase 4: Collect results (all contexts still open)
    print(f"  Collecting results from {len(open_contexts)} contexts...")
    for ctx_data in open_contexts:
        page = ctx_data["page"]
        profile = ctx_data["profile"]
        try:
            test_error = await page.evaluate("window.__testError__")
            if test_error:
                pr = {"profile": profile, "results": None, "matchResults": [], "grade": "F", "passCount": 0, "totalChecks": 0, "error": test_error}
            else:
                results = await page.evaluate("window.__testResults__")
                adjust_cross_os_font_checks(profile, results)
                match_results = compute_match_results(profile, results)
                pass_count, total_checks = count_all_checks(profile, results, match_results)
                grade = compute_grade(pass_count, total_checks)
                pr = {"profile": profile, "results": results, "matchResults": match_results, "grade": grade, "passCount": pass_count, "totalChecks": total_checks}
        except Exception as e:
            pr = {"profile": profile, "results": None, "matchResults": [], "grade": "F", "passCount": 0, "totalChecks": 0, "error": str(e)}

        profile_results.append(pr)
        print_profile_result(pr)

    # Phase 5: Cross-context re-verification (5s drift check)
    if len(open_contexts) > 1:
        print("  Re-verifying all contexts after 5 seconds for cross-contamination...")
        await asyncio.sleep(5)

        re_verify_script = """(() => ({
          platform: navigator.platform,
          oscpu: navigator.oscpu || "",
          hardwareConcurrency: navigator.hardwareConcurrency || 0,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          screenWidth: screen.width,
          screenHeight: screen.height,
        }))()"""

        for ctx_data in open_contexts:
            page = ctx_data["page"]
            profile = ctx_data["profile"]
            pr = next((r for r in profile_results if r["profile"] is profile), None)
            if not pr or not pr.get("results"):
                continue
            try:
                recheck = await page.evaluate(re_verify_script)
                original = pr["results"]["fingerprints"]
                drifted = []

                if recheck["platform"] != original["navigator"]["platform"]:
                    drifted.append(f"platform: {original['navigator']['platform']} -> {recheck['platform']}")
                if recheck["oscpu"] != original["navigator"]["oscpu"]:
                    drifted.append(f"oscpu: {original['navigator']['oscpu']} -> {recheck['oscpu']}")
                if recheck["hardwareConcurrency"] != original["navigator"]["hardwareConcurrency"]:
                    drifted.append(f"hwc: {original['navigator']['hardwareConcurrency']} -> {recheck['hardwareConcurrency']}")
                if recheck["timezone"] != original["timezone"]["timezone"]:
                    drifted.append(f"timezone: {original['timezone']['timezone']} -> {recheck['timezone']}")
                if recheck["screenWidth"] != original["screen"]["width"]:
                    drifted.append(f"screenWidth: {original['screen']['width']} -> {recheck['screenWidth']}")
                if recheck["screenHeight"] != original["screen"]["height"]:
                    drifted.append(f"screenHeight: {original['screen']['height']} -> {recheck['screenHeight']}")

                if drifted:
                    pr["results"]["stability"]["stable"] = False
                    pr["results"]["stability"]["detail"] = f"Cross-context drift after 5s: {', '.join(drifted)}"
                    pr["passCount"] -= 1
                    pr["grade"] = compute_grade(pr["passCount"], pr["totalChecks"])
                    print(f"  {RED}⚠ Cross-context contamination: {profile['name']}: {', '.join(drifted)}{RESET}")
            except Exception:
                pass

    # Phase 6: Close all contexts
    for ctx_data in open_contexts:
        try:
            await ctx_data["context"].close()
        except Exception:
            pass


# ─── Main Test Runner ─────────────────────────────────────────────────────────

async def run_tests(
    binary_path: str,
    profile_count: int,
    secret: str,
    save_cert: Optional[str],
    no_cert: bool,
) -> int:
    project_dir = Path(__file__).parent.parent

    # 1. Ensure bundle exists
    ensure_bundle(project_dir)

    # 2. Generate fingerprint presets
    print("\nGenerating fingerprint presets via Camoufox Python API...")
    presets = generate_presets()
    print("Presets generated.")

    # 3. Inject timezones and WebRTC
    all_presets_flat = (
        presets["macPerContext"] + presets["linuxPerContext"]
        + [presets["macGlobal"], presets["linuxGlobal"]]
    )
    for i, p in enumerate(all_presets_flat):
        inject_timezone(p, TEST_TIMEZONES[i % len(TEST_TIMEZONES)])
        inject_webrtc_ip(p)

    # 4. Build profile entries
    per_context_entries = []
    for i, p in enumerate(presets["macPerContext"]):
        per_context_entries.append({
            "preset": p,
            "profile": preset_to_profile_config(p, f"macOS Per-Context {chr(65 + i)}", "macos", "per-context"),
        })
    for i, p in enumerate(presets["linuxPerContext"]):
        per_context_entries.append({
            "preset": p,
            "profile": preset_to_profile_config(p, f"Linux Per-Context {chr(65 + i)}", "linux", "per-context"),
        })
    global_entries = [
        {"preset": presets["macGlobal"], "profile": preset_to_profile_config(presets["macGlobal"], "macOS Global", "macos", "global")},
        {"preset": presets["linuxGlobal"], "profile": preset_to_profile_config(presets["linuxGlobal"], "Linux Global", "linux", "global")},
    ]

    # Apply profile count limit
    per_context_count = min(profile_count, len(per_context_entries))
    global_count = min(max(0, profile_count - len(per_context_entries)), len(global_entries))
    per_context_entries = per_context_entries[:per_context_count]
    global_entries = global_entries[:global_count]
    total_profiles = len(per_context_entries) + len(global_entries)

    # 5. Start HTTP server
    port = start_http_server(project_dir / "scripts")
    test_page_url = f"http://127.0.0.1:{port}/test"
    print(f"HTTP server started on port {port}")

    # 6. WSL detection
    needs_wsl = sys.platform == "win32" and is_elf_binary(binary_path)
    if needs_wsl:
        host_ip = get_windows_host_ip()
        test_page_url = re.sub(r"127\.0\.0\.1|localhost", host_ip, test_page_url)
        print(f"WSL mode: using host IP {host_ip}")

    profile_results: list = []
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "ERROR: playwright Python package not installed.\n"
            "  Run: pip install playwright && python -m playwright install firefox\n"
            "  (or: bash scripts/setup.sh)",
            file=sys.stderr,
        )
        return 1

    async with async_playwright() as pw:
        firefox = pw.firefox

        # ── Per-context phase ──────────────────────────────────────────────
        if per_context_entries:
            print(f"\n{'─' * 60}")
            print(f"Per-context phase: {len(per_context_entries)} profiles (all open simultaneously)")
            print(f"{'─' * 60}")
            print("Launching browser...")

            try:
                browser = await firefox.launch(
                    executable_path=binary_path,
                    headless=True,
                    firefox_user_prefs=FIREFOX_WEBGL_PREFS,
                )
            except Exception as e:
                print(f"{RED}ERROR: Failed to launch Camoufox: {e}{RESET}", file=sys.stderr)
                return 1

            try:
                await run_per_context_phase(browser, per_context_entries, test_page_url, profile_results)
            finally:
                await browser.close()

        # ── Global phase ───────────────────────────────────────────────────
        if global_entries:
            print(f"\n{'─' * 60}")
            print("Global phase: separate browser per profile")
            print(f"{'─' * 60}")

        for entry in global_entries:
            preset = entry["preset"]
            profile = entry["profile"]
            print(f"\nLaunching browser for: {profile['name']}")

            browser = None
            try:
                env = {**dict(os.environ), "CAMOU_CONFIG": json.dumps(preset["camouConfig"])}
                browser = await firefox.launch(
                    executable_path=binary_path,
                    headless=True,
                    env=env,
                    firefox_user_prefs=FIREFOX_WEBGL_PREFS,
                )

                vp = preset["contextOptions"].get("viewport")
                context = await browser.new_context(
                    viewport=(
                        {"width": min(vp["width"], 1920), "height": min(vp["height"], 1080)}
                        if vp else {"width": 1920, "height": 1080}
                    ),
                )

                # Inject only WebRTC IP for global profiles (CAMOU_CONFIG handles everything else)
                await context.add_init_script(
                    f"try {{ if (typeof window.setWebRTCIPv4 === 'function') window.setWebRTCIPv4({json.dumps(WEBRTC_TEST_IP)}); }} catch(e) {{}}"
                )

                page = await context.new_page()
                await page.goto(test_page_url, wait_until="domcontentloaded", timeout=30000)
                print(f"  Waiting for tests to complete...")
                await page.wait_for_function("!!window.__testComplete__", timeout=120000)

                test_error = await page.evaluate("window.__testError__")
                if test_error:
                    pr = {"profile": profile, "results": None, "matchResults": [], "grade": "F", "passCount": 0, "totalChecks": 0, "error": test_error}
                else:
                    results = await page.evaluate("window.__testResults__")
                    adjust_cross_os_font_checks(profile, results)
                    results["selfDestruct"] = None  # Not applicable for global profiles
                    match_results = compute_match_results(profile, results)
                    pass_count, total_checks = count_all_checks(profile, results, match_results)
                    grade = compute_grade(pass_count, total_checks)
                    pr = {"profile": profile, "results": results, "matchResults": match_results, "grade": grade, "passCount": pass_count, "totalChecks": total_checks}

                await browser.close()
                browser = None

            except Exception as e:
                pr = {"profile": profile, "results": None, "matchResults": [], "grade": "F", "passCount": 0, "totalChecks": 0, "error": str(e)}
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass

            profile_results.append(pr)
            print_profile_result(pr)

    # ── Final summary ──────────────────────────────────────────────────────
    cross_profile = compute_cross_profile(profile_results)
    total_passed = sum(p["passCount"] for p in profile_results)
    total_checks_sum = sum(p["totalChecks"] for p in profile_results)
    overall_grade = compute_grade(total_passed, total_checks_sum)

    full_result = {
        "profiles": profile_results,
        "crossProfile": cross_profile,
        "overallGrade": overall_grade,
        "totalPassed": total_passed,
        "totalChecks": total_checks_sum,
        "timestamp": timestamp,
        "binaryPath": binary_path,
    }

    print(f"\n{'═' * 62}")
    gc = grade_color(overall_grade)
    print(f"OVERALL: {gc}{BOLD}[{overall_grade}]{RESET}  {total_passed}/{total_checks_sum} checks passed  ({total_profiles} profiles)")
    print(f"{'═' * 62}")

    if not no_cert:
        cert = generate_certificate(full_result, secret)
        print_certificate(cert, cross_profile, overall_grade)

        if save_cert:
            cert_text = build_certificate_text(cert, cross_profile, overall_grade)
            Path(save_cert).write_text(cert_text, encoding="utf-8")
            print(f"Certificate saved to: {save_cert}")

    return 0 if total_passed == total_checks_sum else 1
