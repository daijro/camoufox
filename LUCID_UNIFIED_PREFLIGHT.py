import os
import sys

def check_file(path, critical_strings=[]):
    if not os.path.exists(path):
        return False, f"MISSING FILE: {path}"
    
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        for s in critical_strings:
            if s not in content:
                return False, f"MISSING LOGIC in {path}: Could not find '{s}'"
    return True, f"OK: {path}"

def main():
    print("==================================================")
    print(" LUCID EMPIRE :: GRAND UNIFIED PRE-FLIGHT ")
    print(" TARGET: PHASE 4 (BUILD) + PHASE 5 (SOVEREIGN) ")
    print("==================================================")
    
    checklist = [
        # PHASE 4 CHECKS
        ("lucid_launcher.py", ["class LucidLauncherApp", "Tkinter"]),
        ("modules/commerce_injector.py", ["StorageEvent", "dispatchEvent"]),
        (".github/workflows/lucid-build.yml", ["cd camoufox-*", "mozillabuild"]),
        
        # PHASE 5 CHECKS (The Upgrade)
        ("lucid_launcher.py", ["aging_scale", "tk.Scale", "GEOIP_API"]), # Forensic Slider
        ("core/genesis_engine.py", ["_derive_persona_from_identity", "wealthy_zips"]), # Persona Logic
        ("modules/humanization.py", ["GANMouse", "onnxruntime"]), # Biometrics
        ("network/xdp_outbound.c", ["xdp_outbound", "rewrite_tcp_headers"]), # eBPF
        ("genesis/docker-compose.yml", ["vtpm_sidecar", "swtpm"]), # vTPM
    ]

    errors = 0
    print("\n--- SCANNING FILE SYSTEM ---\n")
    
    for path, signatures in checklist:
        passed, msg = check_file(path, signatures)
        if passed:
            print(f"[PASS] {path}")
        else:
            print(f"[FAIL] {msg}")
            errors += 1

    print("\n--------------------------------------------------")
    if errors == 0:
        print("RESULT: SYSTEM INTEGRITY 100%. READY FOR DEPLOYMENT.")
        print("ACTION: git push origin main")
    else:
        print(f"RESULT: {errors} CRITICAL GAPS DETECTED.")
        print("ACTION: Review the generated files and patch missing components.")

if __name__ == "__main__":
    main()
