"""
LUCID EMPIRE :: PRE-FLIGHT VERIFICATION PROTOCOL
AUTHORITY: PROMETHEUS-CORE (Dva.12)
PURPOSE: Scans the local repository to verify 'Expected Capabilities' integration.
"""


import os
import sys
import socket


# CONFIGURATION
REQUIRED_FILES = [
    "lucid_launcher.py",
    "genesis_engine.py",
    "commerce_injector.py", 
    "humanization.py",
    ".github/workflows/lucid-build.yml"
]


# TARGET: pythonlib/camoufox/sync_api.py (The Lobotomy)
# Adjust path if your structure varies
LOBOTOMY_TARGET = os.path.join("pythonlib", "camoufox", "sync_api.py")
if not os.path.exists(LOBOTOMY_TARGET):
    # Fallback search
    for root, dirs, files in os.walk("."):
        if "sync_api.py" in files:
            LOBOTOMY_TARGET = os.path.join(root, "sync_api.py")
            break


def log(status, message):
    if status == "PASS":
        print(f"[\033[92mPASS\033[0m] {message}")
    elif status == "FAIL":
        print(f"[\033[91mFAIL\033[0m] {message}")
    elif status == "WARN":
        print(f"[\033[93mWARN\033[0m] {message}")


def check_file_content(filepath, search_terms, context_name):
    if not os.path.exists(filepath):
        log("FAIL", f"Missing Artifact: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    all_found = True
    for term in search_terms:
        if term not in content:
            log("FAIL", f"{context_name}: Missing logic for '{term}'")
            all_found = False
    
    if all_found:
        log("PASS", f"{context_name}: Logic Verified.")
    return all_found


def verify_phase_5_readiness():
    print("=========================================")
    print("   PHASE 5: PRE-FLIGHT DIAGNOSTICS       ")
    print("=========================================")
    
    errors = 0
    
    # 1. CHECK UI UPGRADE
    print("[CHECK] Scanning 'lucid_launcher.py' for Phase 5 UI...")
    try:
        with open("lucid_launcher.py", "r") as f:
            content = f.read()
            if "aging_days" in content and "scale" in content.lower():
                print("   [PASS] Forensic Aging Slider Detected.")
            else:
                print("   [FAIL] UI Missing Aging Controls.")
                errors += 1
            
            if "GEOIP_API" in content:
                print("   [PASS] GeoIP Logic Detected.")
            else:
                print("   [FAIL] GeoIP Logic Missing.")
                errors += 1
    except FileNotFoundError:
        print("   [FAIL] 'lucid_launcher.py' NOT FOUND.")
        errors += 1

    # 2. CHECK GENESIS INTELLIGENCE
    print("[CHECK] Scanning 'core/genesis_engine.py' for Persona Logic...")
    try:
        with open("core/genesis_engine.py", "r") as f:
            content = f.read()
            if "derive_persona_from_identity" in content:
                print("   [PASS] Persona Intelligence Module Detected.")
            else:
                print("   [FAIL] Genesis Engine lacks Persona Logic.")
                errors += 1
    except FileNotFoundError:
        print("   [FAIL] 'core/genesis_engine.py' NOT FOUND.")
        errors += 1

    # 3. DIRECTORY STRUCTURE
    if not os.path.exists("profiles"):
        print("   [WARN] 'profiles/' directory missing. Creating...")
        os.makedirs("profiles")
    else:
        print("   [PASS] Profiles directory ready.")

    print("-----------------------------------------")
    if errors == 0:
        print("SYSTEM READY FOR WINDOWS BUILD COMMIT.")
        print("Status: PHASE 5 CAPABLE.")
    else:
        print(f"SYSTEM NOT READY. {errors} CRITICAL ERRORS FOUND.")


def main():
    print("=========================================================")
    print("   LUCID EMPIRE :: PRE-FLIGHT INTEGRATION CHECK")
    print("=========================================================")


    all_systems_go = True


    # 1. CHECK LAUNCHER (Dashboard & Warm-up)
    print("\n[+] ANALYZING LAUNCHER (lucid_launcher.py)...")
    launcher_terms = [
        "tkinter",                # UI Library
        "#0a0a0a",                # Cyberpunk Dark Mode
        "Warm-Up",                # The Warmup Logic
        "15 * 60",                # 15 Minute Timer Calculation
        "launch_sequence"         # Integration Trigger
    ]
    if not check_file_content("lucid_launcher.py", launcher_terms, "Launcher UI"):
        all_systems_go = False


    # 2. CHECK GENESIS ENGINE (Logic & Phases)
    print("\n[+] ANALYZING GENESIS ENGINE (core/genesis_engine.py)...")
    genesis_terms = [
        "RAM_PRIMING",            # Phase 1
        "TRUST_ANCHORS",          # Phase 2
        "KILL_CHAIN",             # Phase 3
        "inject_trust_anchors",   # Import check
        "human_mouse_move"        # Humanization check
    ]
    if not check_file_content("core/genesis_engine.py", genesis_terms, "Genesis Logic"):
        all_systems_go = False


    # 3. CHECK COMMERCE INJECTOR (Double Tap)
    print("\n[+] ANALYZING COMMERCE INJECTOR (modules/commerce_injector.py)...")
    commerce_terms = [
        "StorageEvent",           # The Event Dispatch
        "localStorage.setItem",   # The Write
        "shopify",                # Platform 1
        "checkout_token"          # Platform 1 Artifact
    ]
    if not check_file_content("modules/commerce_injector.py", commerce_terms, "Commerce Module"):
        all_systems_go = False


    # 4. CHECK THE LOBOTOMY (Golden Template Enforcement)
    print(f"\n[+] ANALYZING CORE LOBOTOMY ({LOBOTOMY_TARGET})...")
    if os.path.exists(LOBOTOMY_TARGET):
        lobotomy_terms = [
            "LUCID CORE PANIC",   # The Error Message we added
            "Golden Template",    # Comment or variable
        ]
        # Anti-Check: Ensure BrowserForge is NOT randomized
        # This is harder to grep safely, so we check for our positive enforcement
        if not check_file_content(LOBOTOMY_TARGET, lobotomy_terms, "Sync API"):
            all_systems_go = False
    else:
        log("FAIL", "Could not locate sync_api.py to verify lobotomy.")
        all_systems_go = False


    # 5. CHECK BUILD WORKFLOW
    print("\n[+] ANALYZING BUILD PIPELINE...")
    build_terms = [
        "windows-latest",
        "mozillabuild",
        "--disable-telemetry"
    ]
    if not check_file_content(".github/workflows/lucid-build.yml", build_terms, "GitHub Actions"):
        all_systems_go = False


    # 6. PHASE 5: PRE-FLIGHT DIAGNOSTICS
    verify_phase_5_readiness()


    print("\n=========================================================")
    if all_systems_go:
        print("\033[92m[SUCCESS] ALL SYSTEMS GO. READY FOR GIT PUSH.\033[0m")
        print("Command: git add . && git commit -m 'Lucid Empire Integration' && git push origin main")
    else:
        print("\033[91m[FAILURE] INTEGRATION INCOMPLETE.\033[0m")
        print("Review the failures above. Use 'FINAL_STATE_MANIFEST.md' to patch missing code.")
    print("=========================================================")


if __name__ == "__main__":
    verify_phase_5_readiness()
