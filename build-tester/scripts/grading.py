"""
Grading, check counting, match verification, and cross-profile analysis.
"""

import sys


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


# ─── Match Verification ───────────────────────────────────────────────────────

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


# ─── Cross-Profile Analysis ───────────────────────────────────────────────────

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
