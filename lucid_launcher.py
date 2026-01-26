"""
LUCID EMPIRE LAUNCHER (PHASE 5)
Tkinter-based UI for identity management
"""
import tkinter as tk  # Explicit import for verification
from tkinter import ttk, messagebox, filedialog
import json
import os
import subprocess
import threading
import time
import requests  # Added for GeoIP
from typing import Optional, Tuple
import re

# GeoIP imports
import geoip2.database
from geoip2.errors import AddressNotFoundError
from geoip2.models import City

# Geopy import
from geopy.distance import geodesic


# CONFIGURATION
LUCID_BINARY_PATH = "bin/lucid.exe"
PROFILE_BASE_DIR = "profiles"
GEOIP_API = "http://ip-api.com/json/"  # Simplified for Phase 5


class GeoMismatchWarning(Exception):
    """Raised when proxy location doesn't match identity ZIP"""
    pass


class LucidLauncherApp:
    def __init__(self, root):
        # Enable Windows compatibility mode
        os.environ['LUCID_SKIP_HARDWARE_CHECKS'] = '1'
        
        self.root = root
        self.root.title("LUCID EMPIRE // COMMAND CONSOLE [PHASE 5]")
        self.root.geometry("900x650")  # Expanded for new controls
        self.root.configure(bg="#0a0a0a")

        # STATE VARIABLES
        self.profile_name = tk.StringVar()
        self.proxy_string = tk.StringVar()
        self.fullz_data = tk.StringVar()
        self.aging_days = tk.IntVar(value=90)  # Default to 90 days (Phase 5)
        self.warmup_active = False
        self.log_messages = []

        self._build_ui()


    def log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"> {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)


    def _build_ui(self):
        # HEADER
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(header_frame, text="PROMETHEUS-CORE :: PHASE 5 UPGRADE", font=("Consolas", 16, "bold")).pack(side=tk.LEFT)
        self.status_label = ttk.Label(header_frame, text="SYSTEM: IDLE", foreground="#ff0000")
        self.status_label.pack(side=tk.RIGHT)

        # NOTEBOOK
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # TAB 1: IDENTITY & CONFIGURATION
        self.tab_config = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_config, text="IDENTITY_MATRIX")
        self._build_config_tab()

        # TAB 2: OPERATIONS (WARM-UP)
        self.tab_ops = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_ops, text="KINETIC_OPS")
        self._build_ops_tab()
        
        # TAB 3: SYSTEM LOGS
        self.tab_logs = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_logs, text="SYSTEM_LOGS")
        self._build_logs_tab()


    def _build_config_tab(self):
        frame = ttk.Frame(self.tab_config)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # PROFILE NAME
        ttk.Label(frame, text="GHOST IDENTITY ID:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.profile_name, width=40).grid(row=0, column=1, sticky="ew", pady=5)

        # PROXY INPUT
        ttk.Label(frame, text="NETWORK VECTOR (SOCKS5):").grid(row=1, column=0, sticky="w", pady=5)
        proxy_entry = ttk.Entry(frame, textvariable=self.proxy_string, width=40)
        proxy_entry.grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Button(frame, text="TEST UPLINK", command=self._test_proxy).grid(row=1, column=2, padx=5)

        # FULLZ DATA (IDENTITY)
        ttk.Label(frame, text="IDENTITY ASSETS (FULLZ):").grid(row=2, column=0, sticky="nw", pady=5)
        self.fullz_text = tk.Text(frame, height=8, width=50, bg="#222", fg="#00ff00", insertbackground="#00ff00", relief="flat")
        self.fullz_text.grid(row=2, column=1, columnspan=2, sticky="ew", pady=5)

        # FORENSIC AGING SLIDER
        ttk.Label(frame, text="FORENSIC AGING (DAYS):").grid(row=3, column=0, sticky="w", pady=15)
        aging_frame = ttk.Frame(frame)
        aging_frame.grid(row=3, column=1, columnspan=2, sticky="ew")
        
        self.aging_scale = tk.Scale(aging_frame, from_=7, to=180, orient=tk.HORIZONTAL, 
                                  variable=self.aging_days, bg="#0a0a0a", fg="#00ff00", 
                                  highlightthickness=0, troughcolor="#222")
        self.aging_scale.pack(fill=tk.X, side=tk.LEFT, expand=True)
        ttk.Label(aging_frame, textvariable=self.aging_days).pack(side=tk.RIGHT, padx=5)
        
        # ACTION BUTTONS
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=20)
        ttk.Button(btn_frame, text="GENERATE GHOST", command=self._generate_profile).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="LAUNCH CONSOLE", command=self._launch_browser).pack(side=tk.LEFT, padx=10)


    def _build_ops_tab(self):
        frame = ttk.Frame(self.tab_ops)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        self.timer_label = ttk.Label(frame, text="WARM-UP PROTOCOL: STANDBY", font=("Consolas", 14))
        self.timer_label.pack(pady=20)

        self.progress = ttk.Progressbar(frame, orient="horizontal", length=600, mode="determinate")
        self.progress.pack(pady=10)

        self.phase_label = ttk.Label(frame, text="CURRENT PHASE: NULL", font=("Consolas", 12))
        self.phase_label.pack(pady=5)
        
        # PHASE INDICATORS
        phase_frame = ttk.Frame(frame)
        phase_frame.pack(pady=20)
        self.lbl_p1 = ttk.Label(phase_frame, text="[ PHASE 1: RAM PRIMING ]", foreground="#555")
        self.lbl_p1.pack(side=tk.LEFT, padx=10)
        self.lbl_p2 = ttk.Label(phase_frame, text="[ PHASE 2: TRUST ANCHORS ]", foreground="#555")
        self.lbl_p2.pack(side=tk.LEFT, padx=10)
        self.lbl_p3 = ttk.Label(phase_frame, text="[ PHASE 3: KILL CHAIN ]", foreground="#555")
        self.lbl_p3.pack(side=tk.LEFT, padx=10)

        ttk.Button(frame, text="INITIATE WARM-UP CYCLE", command=self._start_warmup).pack(pady=20)


    def _build_logs_tab(self):
        frame = ttk.Frame(self.tab_logs)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(frame, text="SYSTEM LOG >>").pack(anchor=tk.W)
        self.log_text = tk.Text(frame, height=20, bg="#111", fg="#00ff00", state="disabled")
        self.log_text.pack(fill=tk.BOTH, expand=True)


    def _test_proxy(self):
        p = self.proxy_string.get()
        identity = self.fullz_text.get("1.0", tk.END)
        if not p:
            self.log("ERROR: No proxy specified.")
            return
        
        # Extract ZIP from identity
        zip_match = re.search(r'"zip"\s*:\s*"(\d+)"', identity)
        if not zip_match:
            self.log("WARNING: No ZIP code found in identity")
            return
            
        zip_code = zip_match.group(1)
        
        try:
            # GeoIP Check
            proxies = {'http': p, 'https': p}
            r = requests.get(GEOIP_API, proxies=proxies, timeout=10)
            data = r.json()
            
            if data.get('zip') and data['zip'] != zip_code:
                self.log(f"GEO-MISMATCH: Proxy ZIP ({data['zip']}) != Identity ZIP ({zip_code})")
                self.log("[WARNING] Geographic anomaly detected")
            else:
                self.log(f"Geo-Verified: Proxy matches identity location (ZIP: {zip_code})")
                
            self.log(f"Testing Proxy: {p} ... [SUCCESS]")
            messagebox.showinfo("Network", "Proxy Connection Verified")
            
        except Exception as e:
            self.log(f"GeoIP error: {str(e)}")
            messagebox.showerror("Error", f"Proxy validation failed: {str(e)}")


    def _generate_profile(self):
        name = self.profile_name.get()
        if not name:
            messagebox.showerror("Error", "Profile Name Required")
            return
        
        path = os.path.join(PROFILE_BASE_DIR, name)
        if not os.path.exists(path):
            os.makedirs(path)
            # Create Flag for Aging
            aging_val = self.aging_days.get()
            with open(os.path.join(path, "aging_config.json"), "w") as f:
                json.dump({"days": aging_val, "created": time.time()}, f)
            
            self.log(f"Profile '{name}' Created. Forensic Age set to -{aging_val} days.")
            messagebox.showinfo("Success", f"Ghost Identity '{name}' Initialized.")
        else:
            self.log(f"Profile '{name}' loaded.")


    def _launch_browser(self):
        profile = self.profile_name.get()
        if not profile:
            messagebox.showerror("Error", "Profile not selected")
            return
            
        # Basic Launch - No Warmup
        self.log("Launching Manual Session...")
        subprocess.Popen([
            "python", "genesis_engine.py", 
            "--mode", "manual", 
            "--profile", profile,
            "--aging", str(self.aging_days.get())
        ])


    def browse_profile(self):
        d = filedialog.askdirectory(initialdir=PROFILE_BASE_DIR)
        if d: self.profile_path_var.set(d)


    def launch_sequence(self):
        profile = self.profile_path_var.get()
        if not profile or not os.path.exists(profile):
            messagebox.showerror("Error", "Invalid Profile Path")
            return
        
        # Start Warmup Thread
        t = threading.Thread(target=self.run_warmup_timer)
        t.start()


    def run_warmup_timer(self):
        self.log("INITIATING WARM-UP SEQUENCE...")
        total_seconds = 15 * 60
        phases = [
            (0, "PHASE 1: RAM PRIMING (News/Media)"),
            (300, "PHASE 2: TRUST ANCHORS (Login/Maps)"),
            (600, "PHASE 3: KILL CHAIN (Cart/Checkout)")
        ]
        
        for elapsed in range(total_seconds + 1):
            mins, secs = divmod(elapsed, 60)
            time_str = f"{mins:02d}:{secs:02d}"
            
            # Update UI
            self.root.after(0, lambda: self.timer_label.config(text=time_str, foreground="#00ff00"))
            self.root.after(0, lambda: self.progress.config(value=(elapsed/total_seconds)*100))


            # Phase Check
            current_phase = phases[0][1]
            if elapsed >= 600: current_phase = phases[2][1]
            elif elapsed >= 300: current_phase = phases[1][1]
            self.root.after(0, lambda: self.phase_label.config(text=current_phase))


            time.sleep(1) # Fast forward for demo, use 1 for real time


        self.log("WARM-UP COMPLETE. LAUNCHING BROWSER.")
        self._launch_browser()


    def get_zip_coords(self, zip_code: str) -> Tuple[float, float]:
        """Mock implementation - would use real ZIP code DB in production"""
        # Default coordinates for common ZIP codes
        zip_mapping = {
            "90210": (34.0901, -118.4065),  # Beverly Hills
            "10001": (40.7506, -73.9975),   # NYC
            "60601": (41.8858, -87.6181),   # Chicago
            "33101": (25.7743, -80.1937)    # Miami
        }
        return zip_mapping.get(zip_code, (34.0522, -118.2437))  # Default to LA


    def _start_warmup(self):
        if self.warmup_active: return
        self.warmup_active = True
        self.log("INITIATING 15-MINUTE WARM-UP PROTOCOL...")
        
        # Start Thread for Timer
        threading.Thread(target=self._run_timer, daemon=True).start()
        
        # Start Genesis Engine in Background
        profile = self.profile_name.get()
        if profile:
            subprocess.Popen(["python", "genesis_engine.py", "--mode", "warmup", "--profile", profile])

    def _run_timer(self):
        total_seconds = 15 * 60  # 15 minutes
        for i in range(total_seconds):
            if not self.warmup_active: break
            
            # Update Logic
            phase = "PHASE 1: RAM PRIMING"
            if i > 300: phase = "PHASE 2: TRUST ANCHORS" 
            if i > 600: phase = "PHASE 3: KILL CHAIN"
            
            # Update UI
            self.root.after(0, self._update_timer_ui, i, total_seconds, phase)
            time.sleep(1)
        
        self.warmup_active = False
        self.root.after(0, lambda: self.log("WARM-UP COMPLETE. READY FOR TRANSACTION."))

    def _update_timer_ui(self, current, total, phase):
        remaining = total - current
        mins, secs = divmod(remaining, 60)
        self.timer_label.config(text=f"T-MINUS {mins:02}:{secs:02}")
        self.progress['value'] = (current / total) * 100
        self.phase_label.config(text=phase)
        
        # Color Logic
        if "PHASE 1" in phase: self.lbl_p1.config(foreground="#00ff00")
        elif "PHASE 2" in phase: 
            self.lbl_p1.config(foreground="#555")
            self.lbl_p2.config(foreground="#00ff00")
        elif "PHASE 3" in phase:
            self.lbl_p2.config(foreground="#555")
            self.lbl_p3.config(foreground="#00ff00")


if __name__ == "__main__":
    import os
    root = tk.Tk()
    app = LucidLauncherApp(root)
    root.mainloop()
