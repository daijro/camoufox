"""
Fingerprint preset generation, injection, and profile config conversion.
"""

import json
import re
import sys

from constants import TEST_TIMEZONES, WEBRTC_TEST_IP


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
            "  Use the wrapper: ./run_tests.sh <binary_path>\n"
            "  Or install manually: pip install -e ../pythonlib",
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
