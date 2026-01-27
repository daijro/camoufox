import os
import sys

# CONFIGURATION: THE GOLDEN STANDARD
# This dictionary defines exactly what must exist for a Phase 4/5 Certified Build.
REQUIREMENTS = {
    "DIRECTORIES": [
        "core",
        "modules",
        "network",
        "genesis",
        "assets",
        ".github/workflows"
    ],
    "FILES": {
        # PHASE 4 CORE
        "lucid_launcher.py": ["aging_scale", "tk.Scale", "GEOIP_API"], # UI + Slider
        "core/genesis_engine.py": ["_derive_persona_from_identity", "wealthy_zips"], # Persona Logic
        "modules/commerce_injector.py": ["StorageEvent", "dispatchEvent"], # Double-Tap
        # PHASE 5 SOVEREIGNTY
        "modules/humanization.py": ["GANMouse", "onnxruntime"], # AI Biometrics
        "assets/ghost_motor_v5.onnx": [], # The AI Brain Model
        "network/xdp_outbound.c": ["xdp_outbound", "rewrite_tcp_headers"], # eBPF Mask
        "genesis/docker-compose.yml": ["vtpm_sidecar", "swtpm"], # vTPM
        # INFRASTRUCTURE
        ".github/workflows/lucid-build.yml": ["multibuild.py setup", "workflow_dispatch"], # Build Logic
        "multibuild.py": [] # The Repo Wrapper Script
    }
}

def check_structure():
    print("\n[1] SCANNING DIRECTORY ARCHITECTURE...")
    missing_dirs = 0
    for d in REQUIREMENTS["DIRECTORIES"]:
        if os.path.exists(d) and os.path.isdir(d):
            print(f" [OK] Directory Found: {d}/")
        else:
            print(f" [FAIL] CRITICAL MISSING DIRECTORY: {d}/")
            missing_dirs += 1
    return missing_dirs

def check_file_integrity():
    print("\n[2] VERIFYING CODE SIGNATURES...")
    missing_files = 0
    integrity_errors = 0
    
    for filename, signatures in REQUIREMENTS["FILES"].items():
        if not os.path.exists(filename):
            print(f" [FAIL] MISSING FILE: {filename}")
            missing_files += 1
            continue
            
        # Check Content signatures
        if signatures:
            try:
                with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    for sig in signatures:
                        if sig not in content:
                            print(f" [WARN] {filename} exists but LACKS Phase 5 Logic: '{sig}'")
                            integrity_errors += 1
                        else:
                            pass # Signature found
                print(f" [OK] {filename} (Verified Phase 5)")
            except Exception as e:
                print(f" [ERR] Could not read {filename}: {e}")
        else:
            print(f" [OK] {filename} (Present)")
            
    return missing_files, integrity_errors

def check_conflicts():
    print("\n[3] CHECKING FOR BUILD CONFLICTS...")
    conflicts = ["windows-build.yml", "build.yml", ".github/workflows/windows-build.yml", ".github/workflows/build.yml"]
    found_conflicts = 0
    for c in conflicts:
        if os.path.exists(c):
            print(f" [ALERT] CONFLICT FOUND: {c} (Delete this!)")
            found_conflicts += 1
    
    if found_conflicts == 0:
        print(" [OK] No conflicting build configurations found.")
    return found_conflicts

def main():
    print("=======================================================")
    print(" LUCID EMPIRE :: GRAND VERIFICATION MASTER (v5.0) ")
    print("=======================================================")
    
    dirs_missed = check_structure()
    files_missed, integrity_errs = check_file_integrity()
    conflicts = check_conflicts()
    
    print("\n=======================================================")
    print(" DIAGNOSTIC RESULTS")
    print("=======================================================")
    
    if dirs_missed == 0 and files_missed == 0 and integrity_errs == 0 and conflicts == 0:
        print("STATUS: GREEN LIGHT [PHASE 4 + 5 CERTIFIED]")
        print("ACTION: You are cleared to push to GitHub.")
        print(" git add .")
        print(" git commit -m 'Deployment: Phase 5 Sovereign Architecture'")
        print(" git push origin main")
    else:
        print(f"STATUS: RED LIGHT ({dirs_missed + files_missed + integrity_errs + conflicts} Issues)")
        print("ACTION: Correct the [FAIL] items above before pushing.")
        if conflicts > 0:
            print(" * DELETE extra .yml files in .github/workflows/")
        if dirs_missed > 0:
            print(" * CREATE missing folders (core, modules) and move files into them.")

if __name__ == "__main__":
    main()
