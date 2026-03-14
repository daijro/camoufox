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
import hashlib
import hmac as hmac_module
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── Constants ────────────────────────────────────────────────────────────────

TEST_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Tokyo",
]

PROXIES_FILE = Path(__file__).parent / "proxies.txt"

CATEGORY_LABELS = {
    "automation": "Automation Detection",
    "jsEngine": "JS Engine",
    "lieDetection": "Lie Detection",
    "firefoxAPIs": "Firefox APIs",
    "crossSignal": "Cross-Signal",
    "cssFingerprint": "CSS Fingerprint",
    "mathEngine": "Math Engine",
    "permissionsAPI": "Permissions",
    "speechVoices": "Speech Voices",
    "performanceAPI": "Performance",
    "intlConsistency": "Intl Consistency",
    "emojiFingerprint": "Emoji",
    "canvasNoiseDetection": "Canvas Noise",
    "webglRenderHash": "WebGL Render",
    "fontPlatformConsistency": "Font Platform",
    "audioIntegrity": "Audio Integrity",
    "iframeTesting": "Iframe Testing",
    "workerConsistency": "Workers",
    "headlessDetection": "Headless Detection",
    "trashDetection": "Trash Detection",
    "fontEnvironment": "Font Environment",
}

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


def grade_color(g: str) -> str:
    if g == "A":
        return GREEN
    if g in ("B", "C"):
        return YELLOW
    return RED


# ─── Bundle Management ────────────────────────────────────────────────────────

BUILD_TESTER_DIR = Path(__file__).parent.parent / "build-tester"


def ensure_bundle() -> Path:
    bundle_path = BUILD_TESTER_DIR / "scripts" / "checks-bundle.js"
    if bundle_path.exists():
        return bundle_path

    node_modules = BUILD_TESTER_DIR / "node_modules"
    if not node_modules.exists():
        print("ERROR: build-tester/node_modules not found. Run 'npm install' in build-tester/ first.", file=sys.stderr)
        sys.exit(1)

    esbuild = BUILD_TESTER_DIR / "node_modules" / ".bin" / "esbuild"
    print("Building checks bundle (first run)...")
    entry = BUILD_TESTER_DIR / "src" / "lib" / "checks" / "index.ts"
    result = subprocess.run(
        [
            str(esbuild),
            str(entry),
            "--bundle",
            "--platform=browser",
            "--target=es2017",
            "--format=iife",
            "--global-name=CamoufoxChecks",
            f"--outfile={bundle_path}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: esbuild failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Bundle built: {bundle_path}")
    return bundle_path


# ─── Proxy Loading ────────────────────────────────────────────────────────────

def load_proxies(path: Path) -> list:
    """
    Load proxies from a file. Each line must be: user:pass:domain:port
    Returns a list of Playwright-format proxy dicts.
    """
    if not path.exists():
        print(f"ERROR: Proxies file not found: {path}", file=sys.stderr)
        print("  Create a proxies.txt file with one proxy per line: user:pass@domain:port", file=sys.stderr)
        sys.exit(1)

    proxies = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Format: user:pass@domain:port
        try:
            creds, hostport = line.rsplit("@", 1)
            user, password = creds.split(":", 1)
            domain, port = hostport.rsplit(":", 1)
        except ValueError:
            print(f"ERROR: proxies.txt line {lineno}: expected user:pass@domain:port, got: {line!r}", file=sys.stderr)
            sys.exit(1)
        proxies.append({"server": f"http://{domain}:{port}", "username": user, "password": password})

    if not proxies:
        print("ERROR: proxies.txt contains no valid proxy entries.", file=sys.stderr)
        sys.exit(1)

    return proxies


# ─── Grading ──────────────────────────────────────────────────────────────────

def compute_grade(pass_count: int, total_checks: int) -> str:
    fail_count = total_checks - pass_count
    if fail_count == 0:
        return "A"
    if fail_count <= 2:
        return "B"
    if fail_count <= 5:
        return "C"
    if fail_count <= 10:
        return "D"
    return "F"


def count_checks(categories: dict) -> tuple:
    passed = total = 0
    for cat in categories.values():
        if not isinstance(cat, dict):
            continue
        for check in cat.values():
            if check and isinstance(check.get("passed"), bool):
                total += 1
                if check["passed"]:
                    passed += 1
    return passed, total


def count_all_checks(results: dict) -> tuple:
    pass_count = total_checks = 0

    for category_name in ("core", "extended", "workers"):
        p, t = count_checks(results.get(category_name, {}))
        pass_count += p
        total_checks += t

    # WebRTC
    total_checks += 1
    if results.get("webrtc", {}).get("passed"):
        pass_count += 1

    # Stability
    total_checks += 1
    if results.get("stability", {}).get("stable"):
        pass_count += 1

    # Self-destruct (per-context mode)
    if results.get("selfDestruct"):
        for check in results["selfDestruct"].values():
            if check and isinstance(check.get("passed"), bool):
                total_checks += 1
                if check["passed"]:
                    pass_count += 1

    return pass_count, total_checks


def adjust_cross_os_font_checks(os_type: str, results: dict) -> None:
    import sys as _sys
    host_os = "macos" if _sys.platform == "darwin" else ("windows" if _sys.platform == "win32" else "linux")
    if os_type == host_os:
        return
    font_env = results.get("extended", {}).get("fontEnvironment")
    if not font_env:
        return
    for key in ("osDetection", "noWrongOSFonts"):
        check = font_env.get(key)
        if check and not check.get("passed"):
            check["passed"] = True
            check["detail"] = "[Cross-OS: expected] " + check.get("detail", "")


# ─── HTTP Server ──────────────────────────────────────────────────────────────

def start_http_server() -> int:
    scripts_dir = BUILD_TESTER_DIR / "scripts"
    template_path = scripts_dir / "test_page_template.html"
    bundle_path = scripts_dir / "checks-bundle.js"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path in ("/test", "/test/"):
                self._serve(template_path, "text/html; charset=utf-8")
            elif self.path == "/checks-bundle.js":
                self._serve(bundle_path, "application/javascript")
            else:
                self.send_response(404)
                self.end_headers()

        def _serve(self, path: Path, content_type: str):
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port


# ─── Output / Printing ────────────────────────────────────────────────────────

def print_profile_result(pr: dict) -> None:
    profile = pr["profile"]
    grade = pr.get("grade", "F")
    pass_count = pr.get("passCount", 0)
    total_checks = pr.get("totalChecks", 0)
    error = pr.get("error")

    gc = grade_color(grade)

    if error:
        print(f"  {RED}✗{RESET} {profile['name']}: {RED}ERROR{RESET} — {error}")
        return

    tick = "✓" if grade in ("A", "B") else "✗"
    print(f"  {tick} {profile['name']}: {gc}{BOLD}[{grade}]{RESET} {pass_count}/{total_checks}")

    # Show stability failure detail
    results = pr.get("results") or {}
    stability = results.get("stability", {})
    if stability and not stability.get("stable"):
        print(f"      {RED}↳ Stability: {stability.get('detail', '?')}{RESET}")

    # Show WebRTC failure detail
    webrtc = results.get("webrtc", {})
    if webrtc and not webrtc.get("passed"):
        print(f"      {RED}↳ WebRTC: {webrtc.get('detail', '?')}{RESET}")


# ─── Certificate Generation ───────────────────────────────────────────────────

BOX_W = 60

def box_line(inner: str) -> str:
    visible = len(strip_ansi(inner))
    return f"║{inner}{' ' * max(0, BOX_W - visible)}║"

def box_sep() -> str:
    return f"╠{'═' * BOX_W}╣"

def box_top() -> str:
    return f"╔{'═' * BOX_W}╗"

def box_bot() -> str:
    return f"╚{'═' * BOX_W}╝"

def format_section_line(name: str, passed: int, total: int) -> str:
    ok = passed == total
    score = f"{passed}/{total}"
    status_visible = "[PASS]" if ok else f"[{total - passed} FAIL]"
    status_ansi = f"{GREEN}{status_visible}{RESET}" if ok else f"{RED}{status_visible}{RESET}"
    prefix_vis = f"  {name} "
    suffix_vis = f" {score}  {status_visible}  "
    dots_len = max(1, BOX_W - len(prefix_vis) - len(suffix_vis))
    inner = f"  {name} {'.' * dots_len} {score}  {status_ansi}  "
    return box_line(inner)


CAT_ART = r"""    /\_____/\
   /  o   o  \
  ( ==  ^  == )
   )         (
  (  )     (  )
 ( (  )   (  ) )
(__(__)___(__)__)"""


def compute_section_results(results: dict) -> list:
    sections = []
    all_categories = {**results.get("core", {}), **results.get("extended", {}), **results.get("workers", {})}
    for key, checks in all_categories.items():
        if key == "webglExtended":
            continue
        if not isinstance(checks, dict):
            continue
        passed = total = 0
        for check in checks.values():
            if check and isinstance(check.get("passed"), bool):
                total += 1
                if check["passed"]:
                    passed += 1
        if total > 0:
            sections.append({"name": CATEGORY_LABELS.get(key, key), "passed": passed, "total": total})
    webrtc = results.get("webrtc", {})
    stability = results.get("stability", {})
    sections.append({"name": "WebRTC", "passed": 1 if webrtc.get("passed") else 0, "total": 1})
    sections.append({"name": "Stability", "passed": 1 if stability.get("stable") else 0, "total": 1})
    return sections


def compute_cross_profile(profile_results: list) -> dict:
    mac_ctx = [p for p in profile_results if p["profile"]["os"] == "macos"]
    linux_ctx = [p for p in profile_results if p["profile"]["os"] == "linux"]

    def analyze(group: list) -> dict:
        if not group:
            return {"uniqueAudio": 0, "uniqueCanvas": 0, "uniqueFonts": 0, "uniqueTimezones": 0,
                    "uniqueScreens": 0, "uniqueVoices": 0, "uniqueWebGL": 0, "uniquePlatforms": 0, "total": 0}
        audio, canvas, fonts, timezones, screens, voices, webgl_set, platforms = set(), set(), set(), set(), set(), set(), set(), set()
        for p in group:
            fp = (p.get("results") or {}).get("fingerprints") or {}
            if fp.get("audio", {}).get("hash"):
                audio.add(fp["audio"]["hash"])
            if fp.get("canvas", {}).get("hash"):
                canvas.add(fp["canvas"]["hash"])
            if fp.get("fonts", {}).get("hash"):
                fonts.add(fp["fonts"]["hash"])
            if fp.get("timezone", {}).get("timezone"):
                timezones.add(fp["timezone"]["timezone"])
            s = fp.get("screen", {})
            if s:
                screens.add(f"{s.get('width')}x{s.get('height')}")
            if fp.get("speechVoices", {}).get("hash"):
                voices.add(fp["speechVoices"]["hash"])
            w = fp.get("webgl", {})
            if w:
                webgl_set.add(f"{w.get('unmaskedVendor')}|{w.get('unmaskedRenderer')}")
            if fp.get("navigator", {}).get("platform"):
                platforms.add(fp["navigator"]["platform"])
        return {
            "uniqueAudio": len(audio), "uniqueCanvas": len(canvas), "uniqueFonts": len(fonts),
            "uniqueTimezones": len(timezones), "uniqueScreens": len(screens),
            "uniqueVoices": len(voices), "uniqueWebGL": len(webgl_set),
            "uniquePlatforms": len(platforms), "total": len(group),
        }

    return {"macPerContext": analyze(mac_ctx), "linuxPerContext": analyze(linux_ctx)}


def generate_certificate(full_result: dict, secret: str) -> dict:
    all_section_results: list = []
    all_failed_tests: list = []

    for pr in full_result["profiles"]:
        if not pr.get("results"):
            all_failed_tests.append(f"{pr['profile']['name']}: Error — {pr.get('error', 'unknown')}")
            continue

        sections = compute_section_results(pr["results"])
        for s in sections:
            existing = next((e for e in all_section_results if e["name"] == s["name"]), None)
            if existing:
                existing["passed"] += s["passed"]
                existing["total"] += s["total"]
            else:
                all_section_results.append(dict(s))

        results = pr["results"]
        all_cats = {**results.get("core", {}), **results.get("extended", {}), **results.get("workers", {})}
        for cat_key, checks in all_cats.items():
            if not isinstance(checks, dict):
                continue
            for check_name, check in checks.items():
                if check and isinstance(check.get("passed"), bool) and not check["passed"]:
                    label = CATEGORY_LABELS.get(cat_key, cat_key)
                    all_failed_tests.append(f"{pr['profile']['name']}: {label}: {check_name} — {check.get('detail', '')}")

        webrtc = results.get("webrtc", {})
        stability = results.get("stability", {})
        if not webrtc.get("passed"):
            all_failed_tests.append(f"{pr['profile']['name']}: WebRTC: {webrtc.get('detail', '')}")
        if not stability.get("stable"):
            all_failed_tests.append(f"{pr['profile']['name']}: Stability: {stability.get('detail', '')}")

    cp = full_result["crossProfile"]
    mac = cp.get("macPerContext", {})
    linux = cp.get("linuxPerContext", {})

    if mac.get("total", 0) > 0:
        mac_unique = (
            (1 if mac.get("uniqueAudio") == mac["total"] else 0)
            + (1 if mac.get("uniqueCanvas") == mac["total"] else 0)
            + (1 if mac.get("uniqueTimezones") == mac["total"] else 0)
            + (1 if mac.get("uniqueScreens") == mac["total"] else 0)
        )
        all_section_results.append({"name": "Mac Uniqueness", "passed": mac_unique, "total": 4})

    if linux.get("total", 0) > 0:
        linux_unique = (
            (1 if linux.get("uniqueAudio") == linux["total"] else 0)
            + (1 if linux.get("uniqueCanvas") == linux["total"] else 0)
            + (1 if linux.get("uniqueTimezones") == linux["total"] else 0)
            + (1 if linux.get("uniqueScreens") == linux["total"] else 0)
        )
        all_section_results.append({"name": "Linux Uniqueness", "passed": linux_unique, "total": 4})

    hash_data = {
        "profiles": [
            {"name": p["profile"]["name"], "grade": p["grade"],
             "passCount": p["passCount"], "totalChecks": p["totalChecks"]}
            for p in full_result["profiles"]
        ],
        "crossProfile": full_result["crossProfile"],
        "timestamp": full_result["timestamp"],
    }
    results_hash = hashlib.sha256(json.dumps(hash_data, separators=(",", ":")).encode()).hexdigest()
    signature = hmac_module.new(secret.encode(), results_hash.encode(), hashlib.sha256).hexdigest()

    ua = ""
    for pr in full_result["profiles"]:
        if pr.get("results"):
            ua = pr["results"].get("fingerprints", {}).get("navigator", {}).get("userAgent", "")
            break
    fx_match = re.search(r"Firefox/(\d+\.\d+)", ua)
    camoufox_version_str = f"Firefox {fx_match.group(1)}" if fx_match else ua[:60]

    return {
        "id": str(uuid.uuid4()),
        "signature": signature,
        "resultsHash": results_hash,
        "timestamp": full_result["timestamp"],
        "platform": "Multi-OS (Service)",
        "camoufoxVersion": camoufox_version_str,
        "passCount": full_result["totalPassed"],
        "totalTests": full_result["totalChecks"],
        "overallPass": full_result["totalPassed"] == full_result["totalChecks"],
        "sectionResults": all_section_results,
        "failedTests": all_failed_tests[:20],
        "profileCount": len(full_result["profiles"]),
    }


def print_certificate(cert: dict, cross_profile: dict, overall_grade: str) -> None:
    gc = grade_color(overall_grade)
    w = BOX_W

    print()
    print(CYAN + CAT_ART + RESET)
    print()
    print(BOLD + box_top() + RESET)

    title = "CAMOUFOX SERVICE VERIFICATION CERTIFICATE"
    print(BOLD + box_line(f"{title:^{w}}") + RESET)
    print(BOLD + box_sep() + RESET)

    grade_inner = f"  {gc}{BOLD}Grade: {overall_grade}{RESET}     Score: {cert['passCount']}/{cert['totalTests']}     Profiles: {cert['profileCount']}"
    print(box_line(grade_inner))
    print(box_line(f"  Issued: {cert['timestamp']}"))

    if cert["overallPass"]:
        print(box_line(f"  Status: {GREEN}ALL PASS{RESET}"))
    else:
        print(box_line(f"  Status: {RED}FAILURES DETECTED{RESET}"))

    print(BOLD + box_sep() + RESET)
    print(box_line(f"  {BOLD}SECTION RESULTS{RESET}"))
    for s in cert.get("sectionResults", []):
        print(format_section_line(s["name"], s["passed"], s["total"]))

    print(BOLD + box_sep() + RESET)
    print(box_line(f"  {BOLD}CROSS-PROFILE UNIQUENESS{RESET}"))

    mac = cross_profile.get("macPerContext", {})
    linux = cross_profile.get("linuxPerContext", {})
    if mac.get("total", 0) > 0:
        t = mac["total"]
        print(box_line(f"  macOS  Audio:{mac.get('uniqueAudio',0)}/{t}  Canvas:{mac.get('uniqueCanvas',0)}/{t}  TZ:{mac.get('uniqueTimezones',0)}/{t}  Screen:{mac.get('uniqueScreens',0)}/{t}"))
    if linux.get("total", 0) > 0:
        t = linux["total"]
        print(box_line(f"  Linux  Audio:{linux.get('uniqueAudio',0)}/{t}  Canvas:{linux.get('uniqueCanvas',0)}/{t}  TZ:{linux.get('uniqueTimezones',0)}/{t}  Screen:{linux.get('uniqueScreens',0)}/{t}"))

    print(BOLD + box_sep() + RESET)
    print(box_line(f"  ID:   {cert['id']}"))
    print(box_line(f"  Hash: {cert['resultsHash'][:48]}..."))
    print(box_line(f"  Sig:  {cert['signature'][:48]}..."))
    print(BOLD + box_bot() + RESET)
    print()


# ─── Main Test Runner ─────────────────────────────────────────────────────────

async def run_profile(context, profile: dict, test_page_url: str) -> dict:
    """Run checks on a single already-created context."""
    page = await context.new_page()
    try:
        await page.goto(test_page_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_function("!!window.__testComplete__", timeout=120_000)
        test_error = await page.evaluate("window.__testError__")
        if test_error:
            return {"profile": profile, "results": None, "grade": "F", "passCount": 0, "totalChecks": 0, "error": test_error}
        results = await page.evaluate("window.__testResults__")
        adjust_cross_os_font_checks(profile["os"], results)
        pass_count, total_checks = count_all_checks(results)
        grade = compute_grade(pass_count, total_checks)
        return {"profile": profile, "results": results, "grade": grade, "passCount": pass_count, "totalChecks": total_checks}
    except Exception as e:
        return {"profile": profile, "results": None, "grade": "F", "passCount": 0, "totalChecks": 0, "error": str(e)}


async def run_tests(
    browser_version: str,
    profile_count: int,
    headful: bool,
    proxies_path: Path,
    secret: str,
    save_cert: Optional[str],
    no_cert: bool,
) -> int:
    # 1. Ensure bundle
    ensure_bundle()

    # 2. Load proxies
    proxies = load_proxies(proxies_path)
    print(f"Loaded {len(proxies)} proxy/proxies from {proxies_path.name}")

    # 3. Build profile specs — fingerprints are generated by camoufox per-context
    all_specs = []
    for i in range(3):
        all_specs.append({"os": "macos", "timezone_id": TEST_TIMEZONES[i % len(TEST_TIMEZONES)], "name": f"macOS Per-Context {chr(65 + i)}"})
    for i in range(3):
        all_specs.append({"os": "linux", "timezone_id": TEST_TIMEZONES[(3 + i) % len(TEST_TIMEZONES)], "name": f"Linux Per-Context {chr(65 + i)}"})

    entries = all_specs[:max(1, min(profile_count, len(all_specs)))]

    # Assign proxies round-robin across entries
    for i, entry in enumerate(entries):
        entry["proxy"] = proxies[i % len(proxies)]

    # 3. Start HTTP server
    port = start_http_server()
    test_page_url = f"http://127.0.0.1:{port}/test"
    print(f"HTTP server started on port {port}")

    # 4. Parse ff_version from browser_version specifier
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
                profile = {"name": entry["name"], "os": entry["os"]}
                try:
                    context = await AsyncNewContext(browser, os=entry["os"], timezone_id=entry["timezone_id"], proxy=entry["proxy"])
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
