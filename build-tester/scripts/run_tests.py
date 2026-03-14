#!/usr/bin/env python3
"""
Camoufox Build Tester — Python CLI

Runs the same antibot-detection checks as the Next.js web app,
but as a standalone CLI with ASCII art certificate output.

Usage:
  python scripts/run_tests.py <binary_path> [options]

Options:
  --profile-count N     Number of profiles to test (1-8, default: 8)
  --secret KEY          HMAC signing key for certificate
  --save-cert PATH      Save certificate text to this file
  --no-cert             Skip certificate generation
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

# ─── Constants ───────────────────────────────────────────────────────────────

TEST_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Tokyo",
    "America/Denver",
    "Australia/Sydney",
]

WEBRTC_TEST_IP = "203.0.113.1"

FIREFOX_WEBGL_PREFS = {
    "webgl.force-enabled": True,
    "webgl.enable-webgl2": True,
}

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

def ensure_bundle(project_dir: Path) -> Path:
    bundle_path = project_dir / "scripts" / "checks-bundle.js"
    if bundle_path.exists():
        return bundle_path

    node_modules = project_dir / "node_modules"
    if not node_modules.exists():
        print("ERROR: node_modules not found. Run 'npm install' first.", file=sys.stderr)
        sys.exit(1)

    esbuild = project_dir / "node_modules" / ".bin" / "esbuild"
    if sys.platform == "win32":
        esbuild_cmd_path = project_dir / "node_modules" / ".bin" / "esbuild.cmd"
        if esbuild_cmd_path.exists():
            esbuild = esbuild_cmd_path

    print("Building checks bundle (first run)...")
    entry = project_dir / "src" / "lib" / "checks" / "index.ts"
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


# ─── Preset Generation ────────────────────────────────────────────────────────

def convert_preset(ctx: dict) -> dict:
    """Convert generate_context_fingerprint() result to camelCase dict."""
    preset = ctx["preset"]
    config = ctx["config"]
    nav = preset.get("navigator", {})
    screen = preset.get("screen", {})
    webgl = preset.get("webgl", {})

    return {
        "initScript": ctx["init_script"],
        "contextOptions": {
            "userAgent": ctx["context_options"].get("user_agent"),
            "viewport": ctx["context_options"].get("viewport"),
            "deviceScaleFactor": ctx["context_options"].get("device_scale_factor"),
            "locale": ctx["context_options"].get("locale"),
            "timezoneId": ctx["context_options"].get("timezone_id"),
        },
        "camouConfig": config,
        "profileConfig": {
            "fontSpacingSeed": config.get("fonts:spacing_seed", 0),
            "audioSeed": config.get("audio:seed", 0),
            "canvasSeed": config.get("canvas:seed", 0),
            "screenWidth": screen.get("width", 1920),
            "screenHeight": screen.get("height", 1080),
            "screenColorDepth": screen.get("colorDepth", 24),
            "navigatorPlatform": nav.get("platform", ""),
            "navigatorOscpu": config.get("navigator.oscpu", ""),
            "navigatorUserAgent": config.get("navigator.userAgent", ""),
            "hardwareConcurrency": nav.get("hardwareConcurrency", 0),
            "webglVendor": webgl.get("unmaskedVendor", ""),
            "webglRenderer": webgl.get("unmaskedRenderer", ""),
            "timezone": config.get("timezone", preset.get("timezone", "")),
            "fontList": config.get("fonts", preset.get("fonts", [])),
            "speechVoices": config.get("voices", preset.get("speechVoices", [])),
        },
    }


def generate_presets() -> dict:
    try:
        from camoufox.fingerprints import generate_context_fingerprint
    except ImportError:
        print(
            "ERROR: camoufox Python package not installed.\n"
            "  Run: pip install camoufox  (or: bash scripts/setup.sh)",
            file=sys.stderr,
        )
        sys.exit(1)

    print("  Generating 3 macOS per-context profiles...")
    mac_per_context = [convert_preset(generate_context_fingerprint(os="macos")) for _ in range(3)]
    print("  Generating 3 Linux per-context profiles...")
    linux_per_context = [convert_preset(generate_context_fingerprint(os="linux")) for _ in range(3)]
    print("  Generating macOS global profile...")
    mac_global = convert_preset(generate_context_fingerprint(os="macos"))
    print("  Generating Linux global profile...")
    linux_global = convert_preset(generate_context_fingerprint(os="linux"))

    return {
        "macPerContext": mac_per_context,
        "linuxPerContext": linux_per_context,
        "macGlobal": mac_global,
        "linuxGlobal": linux_global,
    }


# ─── Preset Injection ─────────────────────────────────────────────────────────

def inject_timezone(preset: dict, timezone: str) -> None:
    preset["initScript"] = re.sub(
        r"w\.setTimezone\(Intl\.DateTimeFormat\(\)\.resolvedOptions\(\)\.timeZone\)",
        f"w.setTimezone({json.dumps(timezone)})",
        preset["initScript"],
    )
    preset["contextOptions"]["timezoneId"] = timezone
    preset["profileConfig"]["timezone"] = timezone
    preset["camouConfig"]["timezone"] = timezone


def inject_webrtc_ip(preset: dict) -> None:
    preset["initScript"] = re.sub(
        r'w\.setWebRTCIPv4\(""\)',
        f"w.setWebRTCIPv4({json.dumps(WEBRTC_TEST_IP)})",
        preset["initScript"],
    )


# ─── Profile Config ───────────────────────────────────────────────────────────

def preset_to_profile_config(preset: dict, name: str, os_type: str, mode: str) -> dict:
    pc = preset["profileConfig"]
    return {
        "name": name,
        "os": os_type,
        "mode": mode,
        "platform": pc["navigatorPlatform"],
        "oscpu": pc["navigatorOscpu"],
        "userAgent": pc["navigatorUserAgent"],
        "hardwareConcurrency": pc["hardwareConcurrency"],
        "screenWidth": pc["screenWidth"],
        "screenHeight": pc["screenHeight"],
        "colorDepth": pc["screenColorDepth"],
        "timezone": pc["timezone"],
        "webglVendor": pc["webglVendor"],
        "webglRenderer": pc["webglRenderer"],
    }


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


def count_all_checks(profile: dict, results: dict, match_results: list) -> tuple:
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

    # Match results
    for m in match_results:
        total_checks += 1
        if m.get("passed"):
            pass_count += 1

    # Self-destruct (per-context only)
    if profile.get("mode") == "per-context" and results.get("selfDestruct"):
        for check in results["selfDestruct"].values():
            if check and isinstance(check.get("passed"), bool):
                total_checks += 1
                if check["passed"]:
                    pass_count += 1

    return pass_count, total_checks


def adjust_cross_os_font_checks(profile: dict, results: dict) -> None:
    host_os = "macos" if sys.platform == "darwin" else ("windows" if sys.platform == "win32" else "linux")
    if profile["os"] == host_os:
        return

    font_env = results.get("extended", {}).get("fontEnvironment")
    if not font_env:
        return

    for key in ("osDetection", "noWrongOSFonts"):
        check = font_env.get(key)
        if check and not check.get("passed"):
            check["passed"] = True
            check["detail"] = "[Cross-OS: expected] " + check.get("detail", "")


def compute_match_results(profile: dict, results: dict) -> list:
    matches = []
    fp = results.get("fingerprints", {})
    nav = fp.get("navigator", {})
    tz = fp.get("timezone", {})
    screen = fp.get("screen", {})
    webgl = fp.get("webgl", {})

    if profile["mode"] == "per-context":
        matches.append({"name": "navigator.userAgent", "passed": nav.get("userAgent") == profile["userAgent"], "expected": profile["userAgent"], "actual": nav.get("userAgent", "")})
        matches.append({"name": "navigator.platform", "passed": nav.get("platform") == profile["platform"], "expected": profile["platform"], "actual": nav.get("platform", "")})
        matches.append({"name": "navigator.oscpu", "passed": nav.get("oscpu") == profile["oscpu"], "expected": profile["oscpu"], "actual": nav.get("oscpu", "")})
        matches.append({"name": "navigator.hardwareConcurrency", "passed": nav.get("hardwareConcurrency") == profile["hardwareConcurrency"], "expected": str(profile["hardwareConcurrency"]), "actual": str(nav.get("hardwareConcurrency", ""))})
        matches.append({"name": "timezone", "passed": tz.get("timezone") == profile["timezone"], "expected": profile["timezone"], "actual": tz.get("timezone", "")})
        matches.append({"name": "screen.width", "passed": screen.get("width") == profile["screenWidth"], "expected": str(profile["screenWidth"]), "actual": str(screen.get("width", ""))})
        matches.append({"name": "screen.height", "passed": screen.get("height") == profile["screenHeight"], "expected": str(profile["screenHeight"]), "actual": str(screen.get("height", ""))})
        if profile.get("webglVendor") and webgl:
            matches.append({"name": "webgl.vendor", "passed": webgl.get("unmaskedVendor") == profile["webglVendor"], "expected": profile["webglVendor"], "actual": webgl.get("unmaskedVendor", "(unavailable)")})
        if profile.get("webglRenderer") and webgl:
            matches.append({"name": "webgl.renderer", "passed": webgl.get("unmaskedRenderer") == profile["webglRenderer"], "expected": profile["webglRenderer"], "actual": webgl.get("unmaskedRenderer", "(unavailable)")})
    else:
        matches.append({"name": "navigator.userAgent (global)", "passed": nav.get("userAgent") == profile["userAgent"], "expected": profile["userAgent"], "actual": nav.get("userAgent", "")})
        matches.append({"name": "navigator.platform (global)", "passed": nav.get("platform") == profile["platform"], "expected": profile["platform"], "actual": nav.get("platform", "")})
        matches.append({"name": "navigator.oscpu (global)", "passed": nav.get("oscpu") == profile["oscpu"], "expected": profile["oscpu"], "actual": nav.get("oscpu", "")})
        matches.append({"name": "hardwareConcurrency (global)", "passed": nav.get("hardwareConcurrency") == profile["hardwareConcurrency"], "expected": str(profile["hardwareConcurrency"]), "actual": str(nav.get("hardwareConcurrency", ""))})
        matches.append({"name": "timezone (global)", "passed": tz.get("timezone") == profile["timezone"], "expected": profile["timezone"], "actual": tz.get("timezone", "")})

    return matches


def compute_cross_profile(profile_results: list) -> dict:
    mac_ctx = [p for p in profile_results if p["profile"]["os"] == "macos" and p["profile"]["mode"] == "per-context"]
    linux_ctx = [p for p in profile_results if p["profile"]["os"] == "linux" and p["profile"]["mode"] == "per-context"]

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


# ─── HTTP Server ──────────────────────────────────────────────────────────────

def start_http_server(scripts_dir: Path) -> int:
    template_path = scripts_dir / "test_page_template.html"
    bundle_path = scripts_dir / "checks-bundle.js"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Suppress access logs

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


# ─── WSL Support ─────────────────────────────────────────────────────────────

def is_elf_binary(file_path: str) -> bool:
    try:
        with open(file_path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except Exception:
        return False


def get_windows_host_ip() -> str:
    try:
        result = subprocess.run(
            ["wsl", "bash", "-lc", "ip route show default"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
        return m.group(1) if m else "localhost"
    except Exception:
        return "localhost"


def windows_to_wsl_path(win_path: str) -> str:
    wsl_m = re.match(r"^[\\\/]{2}(?:wsl\$|wsl\.localhost)[\\\/][^\\\/]+[\\\/](.*)", win_path, re.IGNORECASE)
    if wsl_m:
        return "/" + wsl_m.group(1).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):\\", win_path)
    if not m:
        return win_path.replace("\\", "/")
    return f"/mnt/{m.group(1).lower()}/{win_path[3:].replace(chr(92), '/')}"


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

    # Show match failures
    for m in pr.get("matchResults", []):
        if not m.get("passed"):
            print(f"      {RED}✗ {m['name']}: expected {m.get('expected', '?')}, got {m.get('actual', '?')}{RESET}")


# ─── Certificate Generation ───────────────────────────────────────────────────

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
            all_failed_tests.append(f"{pr['profile']['name']}: Stability: Fingerprints changed between runs (unstable)")

        for m in pr.get("matchResults", []):
            if not m.get("passed"):
                all_failed_tests.append(f"{pr['profile']['name']}: {m['name']} expected {m.get('expected')}, got {m.get('actual')}")

    # Cross-profile uniqueness sections
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

    # Compute results hash (matching Certificate.tsx)
    hash_data = {
        "profiles": [
            {
                "name": p["profile"]["name"],
                "grade": p["grade"],
                "passCount": p["passCount"],
                "totalChecks": p["totalChecks"],
            }
            for p in full_result["profiles"]
        ],
        "crossProfile": full_result["crossProfile"],
        "timestamp": full_result["timestamp"],
    }
    results_hash = hashlib.sha256(json.dumps(hash_data, separators=(",", ":")).encode()).hexdigest()

    # HMAC-SHA256 signature
    signature = hmac_module.new(secret.encode(), results_hash.encode(), hashlib.sha256).hexdigest()

    # Extract user agent
    ua = ""
    for pr in full_result["profiles"]:
        if pr.get("results"):
            ua = pr["results"].get("fingerprints", {}).get("navigator", {}).get("userAgent", "")
            break

    fx_match = re.search(r"Firefox/(\d+\.\d+)", ua)
    camoufox_version = f"Firefox {fx_match.group(1)}" if fx_match else ua[:60]

    return {
        "id": str(uuid.uuid4()),
        "signature": signature,
        "resultsHash": results_hash,
        "timestamp": full_result["timestamp"],
        "platform": "Multi-OS",
        "camoufoxVersion": camoufox_version,
        "passCount": full_result["totalPassed"],
        "totalTests": full_result["totalChecks"],
        "overallPass": full_result["totalPassed"] == full_result["totalChecks"],
        "sectionResults": all_section_results,
        "failedTests": all_failed_tests[:20],
        "profileCount": len(full_result["profiles"]),
    }


# ─── ASCII Certificate Display ────────────────────────────────────────────────

CAT_ART = r"""    /\_____/\
   /  o   o  \
  ( ==  ^  == )
   )         (
  (  )     (  )
 ( (  )   (  ) )
(__(__)___(__)__)"""

BOX_W = 60  # inner visible width of the certificate box


def box_line(inner: str) -> str:
    """Pad inner content to BOX_W visible characters and wrap in box borders."""
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


def build_certificate_text(cert: dict, cross_profile: dict, overall_grade: str) -> str:
    """Build the full ASCII certificate as a plain-text string (no ANSI)."""
    lines = []
    w = BOX_W

    lines.append(CAT_ART)
    lines.append("")
    lines.append(f"╔{'═' * w}╗")

    title = "CAMOUFOX BUILD VERIFICATION CERTIFICATE"
    lines.append(f"║{title:^{w}}║")
    lines.append(f"╠{'═' * w}╣")

    grade_line = f"  Grade: {overall_grade}     Score: {cert['passCount']}/{cert['totalTests']}     Profiles: {cert['profileCount']}"
    lines.append(f"║{grade_line:<{w}}║")
    ts = cert["timestamp"]
    lines.append(f"║  Issued: {ts:<{w-10}}║")
    status_text = "ALL PASS" if cert["overallPass"] else "FAILURES DETECTED"
    lines.append(f"║  Status: {status_text:<{w-10}}║")

    lines.append(f"╠{'═' * w}╣")
    lines.append(f"║{'  SECTION RESULTS':<{w}}║")

    for s in cert.get("sectionResults", []):
        name = s["name"]
        passed = s["passed"]
        total = s["total"]
        score = f"{passed}/{total}"
        status = "[PASS]" if passed == total else f"[{total - passed} FAIL]"
        prefix = f"  {name} "
        suffix = f" {score}  {status}  "
        dots = "." * max(1, w - len(prefix) - len(suffix))
        line = f"{prefix}{dots}{suffix}"
        lines.append(f"║{line:<{w}}║")

    lines.append(f"╠{'═' * w}╣")
    lines.append(f"║{'  CROSS-PROFILE UNIQUENESS':<{w}}║")

    mac = cross_profile.get("macPerContext", {})
    linux = cross_profile.get("linuxPerContext", {})
    if mac.get("total", 0) > 0:
        t = mac["total"]
        line = f"  macOS  Audio:{mac.get('uniqueAudio', 0)}/{t}  Canvas:{mac.get('uniqueCanvas', 0)}/{t}  TZ:{mac.get('uniqueTimezones', 0)}/{t}  Screen:{mac.get('uniqueScreens', 0)}/{t}"
        lines.append(f"║{line:<{w}}║")
    if linux.get("total", 0) > 0:
        t = linux["total"]
        line = f"  Linux  Audio:{linux.get('uniqueAudio', 0)}/{t}  Canvas:{linux.get('uniqueCanvas', 0)}/{t}  TZ:{linux.get('uniqueTimezones', 0)}/{t}  Screen:{linux.get('uniqueScreens', 0)}/{t}"
        lines.append(f"║{line:<{w}}║")

    lines.append(f"╠{'═' * w}╣")
    cert_id = cert["id"]
    results_hash = cert["resultsHash"]
    signature = cert["signature"]
    lines.append(f"║  ID:   {cert_id:<{w-8}}║")
    lines.append(f"║  Hash: {results_hash[:48]}...{'':<{w - 56}}║")
    lines.append(f"║  Sig:  {signature[:48]}...{'':<{w - 56}}║")
    lines.append(f"╚{'═' * w}╝")

    return "\n".join(lines)


def print_certificate(cert: dict, cross_profile: dict, overall_grade: str) -> None:
    gc = grade_color(overall_grade)
    w = BOX_W

    print()
    print(CYAN + CAT_ART + RESET)
    print()
    print(BOLD + box_top() + RESET)

    title = "CAMOUFOX BUILD VERIFICATION CERTIFICATE"
    print(BOLD + box_line(f"{title:^{w}}") + RESET)
    print(BOLD + box_sep() + RESET)

    # Grade / score line
    grade_inner = f"  {gc}{BOLD}Grade: {overall_grade}{RESET}     Score: {cert['passCount']}/{cert['totalTests']}     Profiles: {cert['profileCount']}"
    print(box_line(grade_inner))

    ts = cert["timestamp"]
    print(box_line(f"  Issued: {ts}"))

    if cert["overallPass"]:
        status_inner = f"  Status: {GREEN}ALL PASS{RESET}"
    else:
        status_inner = f"  Status: {RED}FAILURES DETECTED{RESET}"
    print(box_line(status_inner))

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
        line = f"  macOS  Audio:{mac.get('uniqueAudio', 0)}/{t}  Canvas:{mac.get('uniqueCanvas', 0)}/{t}  TZ:{mac.get('uniqueTimezones', 0)}/{t}  Screen:{mac.get('uniqueScreens', 0)}/{t}"
        print(box_line(line))
    if linux.get("total", 0) > 0:
        t = linux["total"]
        line = f"  Linux  Audio:{linux.get('uniqueAudio', 0)}/{t}  Canvas:{linux.get('uniqueCanvas', 0)}/{t}  TZ:{linux.get('uniqueTimezones', 0)}/{t}  Screen:{linux.get('uniqueScreens', 0)}/{t}"
        print(box_line(line))

    print(BOLD + box_sep() + RESET)
    cert_id = cert["id"]
    results_hash = cert["resultsHash"]
    signature = cert["signature"]
    print(box_line(f"  ID:   {cert_id}"))
    print(box_line(f"  Hash: {results_hash[:48]}..."))
    print(box_line(f"  Sig:  {signature[:48]}..."))
    print(BOLD + box_bot() + RESET)
    print()


# ─── Playwright Test Runner ───────────────────────────────────────────────────

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


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Camoufox Build Tester — runs antibot-detection checks via Playwright",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("binary_path", help="Path to the Camoufox (Firefox) binary")
    parser.add_argument(
        "--profile-count", type=int, default=8, metavar="N",
        help="Number of profiles to test, 1-8 (default: 8)",
    )
    parser.add_argument(
        "--secret", default="camoufox-tester-dev-secret", metavar="KEY",
        help="HMAC signing key for the certificate (default: dev secret)",
    )
    parser.add_argument(
        "--save-cert", metavar="PATH",
        help="Save the ASCII certificate to this file",
    )
    parser.add_argument(
        "--no-cert", action="store_true",
        help="Skip certificate generation",
    )
    args = parser.parse_args()

    profile_count = max(1, min(8, args.profile_count))

    binary_path = args.binary_path
    # Resolve macOS .app bundle to internal binary
    if sys.platform == "darwin" and binary_path.endswith(".app"):
        candidate = os.path.join(binary_path, "Contents", "MacOS", "camoufox")
        if os.path.isfile(candidate):
            binary_path = candidate
        else:
            candidate2 = os.path.join(binary_path, "Contents", "MacOS", "firefox")
            if os.path.isfile(candidate2):
                binary_path = candidate2

    if not os.path.isfile(binary_path):
        print(f"ERROR: Binary not found: {binary_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Camoufox Build Tester")
    print(f"Binary:   {binary_path}")
    print(f"Profiles: {profile_count}")

    exit_code = asyncio.run(
        run_tests(
            binary_path=binary_path,
            profile_count=profile_count,
            secret=args.secret,
            save_cert=args.save_cert,
            no_cert=args.no_cert,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
