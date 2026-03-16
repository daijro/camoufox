import hashlib
import hmac as hmac_module
import json
import re
import uuid

from _constants import (
    BOLD, BOX_W, CAT_ART, CATEGORY_LABELS, CYAN, GREEN, RED, RESET,
    box_bot, box_line, box_sep, box_top, grade_color,
)
from _grading import compute_grade, count_checks


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

    results = pr.get("results") or {}
    stability = results.get("stability", {})
    if stability and not stability.get("stable"):
        print(f"      {RED}↳ Stability: {stability.get('detail', '?')}{RESET}")

    webrtc = results.get("webrtc", {})
    if webrtc and not webrtc.get("passed"):
        print(f"      {RED}↳ WebRTC: {webrtc.get('detail', '?')}{RESET}")


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
        audio, canvas, fonts, timezones, screens, voices, webgl_set, platforms = (
            set(), set(), set(), set(), set(), set(), set(), set()
        )
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
                    all_failed_tests.append(
                        f"{pr['profile']['name']}: {label}: {check_name} — {check.get('detail', '')}"
                    )

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

    proxy_info = []
    for pr in full_result["profiles"]:
        geo = pr["profile"].get("proxy_geo", {})
        proxy_info.append({
            "name": pr["profile"]["name"],
            "ip": geo.get("query", "?"),
            "city": geo.get("city", "?"),
            "country": geo.get("country", "?"),
            "timezone": geo.get("timezone", "?"),
        })

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
        "proxyInfo": proxy_info,
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

    proxy_info = cert.get("proxyInfo", [])
    if proxy_info:
        print(BOLD + box_sep() + RESET)
        print(box_line(f"  {BOLD}PROXY DEBUG{RESET}"))
        for pi in proxy_info:
            short_name = pi["name"].replace(" Per-Context", "")
            ip = pi["ip"]
            tz = pi["timezone"]
            city_country = f"{pi['city']}, {pi['country']}"
            print(box_line(f"  {CYAN}{short_name:<9}{RESET}  {ip:<15}  {tz}"))
            print(box_line(f"  {'':<11}{city_country}"))

    print(BOLD + box_sep() + RESET)
    print(box_line(f"  ID:   {cert['id']}"))
    print(box_line(f"  Hash: {cert['resultsHash'][:48]}..."))
    print(box_line(f"  Sig:  {cert['signature'][:48]}..."))
    print(BOLD + box_bot() + RESET)
    print()
