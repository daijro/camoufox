#!/usr/bin/env python3
"""
Camoufox Service Tester — Python CLI

Tests an official Camoufox release (installed via pip) using the same
antibot-detection checks as the build-tester, but launched via the
camoufox Python API instead of a raw binary path.

Usage:
  python run_tests.py [options]

Options:
  --browser-version VER   Camoufox version specifier (default: official/stable)
                          e.g. official/prerelease/146.0.1-beta.50
  --profile-count N       Number of profiles to test (1-6, default: 6)
  --headful               Run with visible browser window
  --proxies PATH          Path to proxies file (default: proxies.txt next to this script)
                          Format: user:pass@domain:port (one per line)
  --secret KEY            HMAC signing key for certificate
  --save-cert PATH        Save certificate text to this file
  --no-cert               Skip certificate generation
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from _bundle import ensure_bundle, start_http_server
from _certificate import (
    compute_cross_profile,
    generate_certificate,
    print_certificate,
    print_profile_result,
)
from _constants import BOLD, RED, RESET, PROXIES_FILE, grade_color
from _grading import adjust_cross_os_font_checks, compute_grade, count_all_checks
from _proxies import load_proxies, resolve_proxy_geo


async def run_tests(
    browser_version: str,
    profile_count: int,
    headful: bool,
    proxies_path: Path,
    secret: str,
    save_cert: Optional[str],
    no_cert: bool,
) -> int:
    # 1. Ensure checks bundle is built
    ensure_bundle()

    # 2. Load proxies
    proxies = load_proxies(proxies_path)
    print(f"Loaded {len(proxies)} proxy/proxies from {proxies_path.name}")

    # 3. Build profile specs — fingerprints and timezone resolved by camoufox per-context
    all_specs = [
        {"os": "macos", "name": f"macOS Per-Context {chr(65 + i)}"} for i in range(3)
    ] + [
        {"os": "linux", "name": f"Linux Per-Context {chr(65 + i)}"} for i in range(3)
    ]
    entries = all_specs[:max(1, min(profile_count, len(all_specs)))]

    # Assign proxies round-robin across entries
    for i, entry in enumerate(entries):
        entry["proxy"] = proxies[i % len(proxies)]

    # Resolve proxy geo info concurrently (for certificate debug section)
    print("Resolving proxy locations...")
    geos = await asyncio.gather(*[resolve_proxy_geo(e["proxy"]) for e in entries])
    for entry, geo in zip(entries, geos):
        entry["proxy_geo"] = geo

    # 4. Start HTTP server for the test page
    port = start_http_server()
    test_page_url = f"http://127.0.0.1:{port}/test"
    print(f"HTTP server started on port {port}")

    # 5. Parse ff_version from browser_version specifier
    ff_version = None
    for part in browser_version.split("/"):
        try:
            ff_version = int(part.split(".")[0])
            break
        except ValueError:
            continue

    profile_results: list = []
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        from camoufox.async_api import AsyncCamoufox, AsyncNewContext
    except ImportError:
        print("ERROR: camoufox package not installed.", file=sys.stderr)
        return 1

    print(f"\n{'─' * 60}")
    print(f"Per-context phase: {len(entries)} profiles (all open simultaneously)")
    print(f"{'─' * 60}")
    print("Launching browser...")

    launch_kwargs = {"headless": not headful}
    if ff_version:
        launch_kwargs["ff_version"] = ff_version

    try:
        async with AsyncCamoufox(**launch_kwargs) as browser:
            # Create all contexts simultaneously — camoufox handles all fingerprint injection
            open_contexts = []
            for entry in entries:
                profile = {"name": entry["name"], "os": entry["os"], "proxy_geo": entry.get("proxy_geo", {})}
                try:
                    context = await AsyncNewContext(browser, os=entry["os"], proxy=entry["proxy"])
                    open_contexts.append({"context": context, "profile": profile})
                except Exception as e:
                    pr = {"profile": profile, "results": None, "grade": "F",
                          "passCount": 0, "totalChecks": 0, "error": str(e)}
                    profile_results.append(pr)
                    print_profile_result(pr)

            if open_contexts:
                # Navigate all pages concurrently
                print(f"  Navigating {len(open_contexts)} contexts to test page...")
                pages = []
                for ctx_data in open_contexts:
                    page = await ctx_data["context"].new_page()
                    pages.append(page)
                    ctx_data["page"] = page

                await asyncio.gather(
                    *[p.goto(test_page_url, wait_until="domcontentloaded", timeout=30_000)
                      for p in pages],
                    return_exceptions=True,
                )

                # Wait for all tests to complete
                print(f"  Waiting for all tests to complete...")
                await asyncio.gather(
                    *[p.wait_for_function("!!window.__testComplete__", timeout=120_000)
                      for p in pages],
                    return_exceptions=True,
                )

                # Collect results
                print(f"  Collecting results from {len(open_contexts)} contexts...")
                for ctx_data in open_contexts:
                    page = ctx_data["page"]
                    profile = ctx_data["profile"]
                    try:
                        test_error = await page.evaluate("window.__testError__")
                        if test_error:
                            pr = {"profile": profile, "results": None, "grade": "F",
                                  "passCount": 0, "totalChecks": 0, "error": test_error}
                        else:
                            results = await page.evaluate("window.__testResults__")
                            adjust_cross_os_font_checks(profile["os"], results)
                            pass_count, total_checks = count_all_checks(results)
                            grade = compute_grade(pass_count, total_checks)
                            pr = {"profile": profile, "results": results, "grade": grade,
                                  "passCount": pass_count, "totalChecks": total_checks}
                    except Exception as e:
                        pr = {"profile": profile, "results": None, "grade": "F",
                              "passCount": 0, "totalChecks": 0, "error": str(e)}

                    profile_results.append(pr)
                    print_profile_result(pr)

                # Close all contexts
                for ctx_data in open_contexts:
                    try:
                        await ctx_data["context"].close()
                    except Exception:
                        pass

    except Exception as e:
        print(f"{RED}ERROR: Failed to launch Camoufox: {e}{RESET}", file=sys.stderr)
        return 1

    # ── Final summary ──────────────────────────────────────────────────────────
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
    }

    print(f"\n{'─' * 60}")
    print(f"Overall Grade: {grade_color(overall_grade)}{BOLD}{overall_grade}{RESET}  "
          f"Score: {total_passed}/{total_checks_sum}  Profiles: {len(profile_results)}")
    print(f"{'─' * 60}")

    if not no_cert:
        cert = generate_certificate(full_result, secret)
        print_certificate(cert, cross_profile, overall_grade)
        if cert.get("failedTests"):
            print(f"{RED}Failed checks:{RESET}")
            for ft in cert["failedTests"]:
                print(f"  {RED}✗{RESET} {ft}")
            print()
        if save_cert:
            Path(save_cert).write_text(
                f"Grade: {overall_grade}\nScore: {total_passed}/{total_checks_sum}\n"
                f"ID: {cert['id']}\nHash: {cert['resultsHash']}\nSig: {cert['signature']}\n"
            )
            print(f"Certificate saved to: {save_cert}")

    return 0 if overall_grade in ("A", "B") else 1


def main():
    parser = argparse.ArgumentParser(description="Camoufox Service Tester")
    parser.add_argument("--browser-version", default="official/stable",
                        help="Camoufox version specifier (default: official/stable)")
    parser.add_argument("--profile-count", type=int, default=6,
                        help="Number of profiles to test (1-6, default: 6)")
    parser.add_argument("--headful", action="store_true",
                        help="Run with visible browser window")
    parser.add_argument("--proxies", default=str(PROXIES_FILE),
                        help=f"Path to proxies file (default: {PROXIES_FILE.name} next to this script)")
    parser.add_argument("--secret", default="camoufox-service-test",
                        help="HMAC signing key for certificate")
    parser.add_argument("--save-cert", default=None,
                        help="Save certificate to this file path")
    parser.add_argument("--no-cert", action="store_true",
                        help="Skip certificate generation")
    args = parser.parse_args()

    sys.exit(asyncio.run(run_tests(
        browser_version=args.browser_version,
        profile_count=args.profile_count,
        headful=args.headful,
        proxies_path=Path(args.proxies),
        secret=args.secret,
        save_cert=args.save_cert,
        no_cert=args.no_cert,
    )))


if __name__ == "__main__":
    main()
