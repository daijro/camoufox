"""
Certificate generation (scoring + HMAC signing) and all ASCII output/display.
"""

import hashlib
import hmac as hmac_module
import json
import re
import uuid

from constants import (
    BOLD, CATEGORY_LABELS, CYAN, GREEN, RED, RESET, YELLOW,
    grade_color, strip_ansi,
)

# ─── Box Drawing ──────────────────────────────────────────────────────────────

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


# ─── Profile Result Printing ──────────────────────────────────────────────────

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
