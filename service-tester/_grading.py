import sys

from _constants import CATEGORY_LABELS


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
    host_os = "macos" if sys.platform == "darwin" else ("windows" if sys.platform == "win32" else "linux")
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
