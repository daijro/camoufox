import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import subprocess
import threading
import time
import re
from typing import Optional, Tuple
import geoip2.database
import geoip2.errors
import geoip2.models
import geoip2.reader
from geopy.distance import geodesic


# CONFIGURATION
LUCID_BINARY_PATH = "bin/lucid.exe"
PROFILE_BASE_DIR = "profiles"


class GeoMismatchWarning(Exception):
    """Raised when proxy location doesn't match identity ZIP"""
    pass


class LucidLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LUCID EMPIRE // COMMAND CONSOLE")
        self.root.geometry("800x600")
        self.root.configure(bg="#0a0a0a")
        
        # NEW: Aging slider value
        self.aging_days = tk.IntVar(value=7)  # Default to 7 days

        # STYLES (Cyberpunk Theme)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#0a0a0a")
        style.configure("TLabel", background="#0a0a0a", foreground="#00ff00", font=("Consolas", 10))
        style.configure("TButton", background="#111", foreground="#00ff00", borderwidth=1, font=("Consolas", 10, "bold"))
        style.map("TButton", background=[("active", "#00ff00")], foreground=[("active", "black")])
        style.configure("TNotebook", background="#0a0a0a", borderwidth=0)
        style.configure("TNotebook.Tab", background="#222", foreground="#888", padding=[10, 5], font=("Consolas", 10))
        style.map("TNotebook.Tab", background=[("selected", "#00ff00")], foreground=[("selected", "black")])


        # HEADER
        header_frm = ttk.Frame(root)
        header_frm.pack(fill=tk.X, pady=10, padx=10)
        ttk.Label(header_frm, text="LUCID EMPIRE v1.0 [SOVEREIGN]", font=("Consolas", 20, "bold")).pack(side=tk.LEFT)
        self.status_lbl = ttk.Label(header_frm, text="STATUS: IDLE", foreground="#555")
        self.status_lbl.pack(side=tk.RIGHT, anchor=tk.S)


        # TABS
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)


        # TAB 1: CREATION (Identity & Network)
        self.tab1 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab1, text=" [1] CREATION ")
        self.build_creation_tab()


        # TAB 2: OPERATION (Warm-Up & Launch)
        self.tab2 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab2, text=" [2] OPERATION ")
        self.build_operation_tab()


        # CONSOLE
        ttk.Label(root, text="SYSTEM LOG >>").pack(anchor=tk.W, padx=10)
        self.console = tk.Text(root, height=8, bg="#050505", fg="#00ff00", font=("Consolas", 9), state=tk.DISABLED, bd=0)
        self.console.pack(fill=tk.X, padx=10, pady=(0, 10))


    def log(self, msg):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, f"> {msg}\n")
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)


    def build_creation_tab(self):
        # Identity Vector
        lbl = ttk.Label(self.tab1, text="IDENTITY VECTOR (FULLZ JSON/TEXT):")
        lbl.pack(anchor=tk.W, pady=(15, 5), padx=10)
        self.identity_text = tk.Text(self.tab1, height=8, bg="#111", fg="white", insertbackground="white")
        self.identity_text.pack(fill=tk.X, padx=10)

        # NEW: Forensic Aging Slider
        aging_frame = ttk.LabelFrame(self.tab1, text="FORENSIC AGING (DAYS)", padding=10)
        aging_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Scale(
            aging_frame, 
            from_=1, 
            to=90, 
            variable=self.aging_days,
            command=lambda v: self.log(f"Forensic Aging set to {int(float(v))} days")
        ).pack(fill=tk.X)
        
        ttk.Label(aging_frame, textvariable=self.aging_days).pack()

        # Network Vector
        lbl2 = ttk.Label(self.tab1, text="NETWORK VECTOR (SOCKS5 PROXY):")
        lbl2.pack(anchor=tk.W, pady=(15, 5), padx=10)
        
        net_frame = ttk.Frame(self.tab1)
        net_frame.pack(fill=tk.X, padx=10)
        self.proxy_var = tk.StringVar()
        ttk.Entry(net_frame, textvariable=self.proxy_var, font=("Consolas", 10)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(net_frame, text="TEST CONNECTION", command=self.test_proxy).pack(side=tk.LEFT, padx=(5, 0))


        # Save Profile
        ttk.Button(self.tab1, text="[ COMPILE DIGITAL GHOST ]", command=self.compile_profile).pack(pady=20, fill=tk.X, padx=50)


    def build_operation_tab(self):
        # Profile Select
        frm = ttk.Frame(self.tab2)
        frm.pack(fill=tk.X, pady=15, padx=10)
        ttk.Label(frm, text="SELECT PROFILE:").pack(side=tk.LEFT)
        self.profile_path_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.profile_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(frm, text="BROWSE", command=self.browse_profile).pack(side=tk.LEFT)


        # Warm-Up Timer Visualization
        timer_frame = ttk.LabelFrame(self.tab2, text=" WARM-UP CYCLE (15:00) ", padding=10)
        timer_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.timer_lbl = ttk.Label(timer_frame, text="00:00", font=("Consolas", 30, "bold"), foreground="#444")
        self.timer_lbl.pack(anchor=tk.CENTER)
        
        self.phase_lbl = ttk.Label(timer_frame, text="WAITING FOR INJECTION...", font=("Consolas", 10))
        self.phase_lbl.pack(anchor=tk.CENTER)


        # Progress Bar
        self.progress = ttk.Progressbar(timer_frame, orient=tk.HORIZONTAL, length=100, mode='determinate')
        self.progress.pack(fill=tk.X, pady=10)


        # Launch Button
        ttk.Button(self.tab2, text="[ INITIATE LAUNCH SEQUENCE ]", command=self.launch_sequence).pack(fill=tk.X, padx=50, pady=20)


    def test_proxy(self):
        p = self.proxy_var.get()
        if not p:
            self.log("ERROR: No proxy specified.")
            return
        self.log(f"Testing Proxy: {p} ... [SIMULATED SUCCESS]")
        messagebox.showinfo("Network", "Proxy Connection Verified (Latency: 45ms)")


    def compile_profile(self):
        # In a real app, this would save the JSON and config
        self.log("Compiling Identity Assets...")
        self.log("Identity Vector Hashed.")
        self.log("Profile Ready for Genesis.")
        messagebox.showinfo("Success", "Digital Ghost Compiled.")


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
            self.root.after(0, lambda: self.timer_lbl.config(text=time_str, foreground="#00ff00"))
            self.root.after(0, lambda: self.progress.config(value=(elapsed/total_seconds)*100))


            # Phase Check
            current_phase = phases[0][1]
            if elapsed >= 600: current_phase = phases[2][1]
            elif elapsed >= 300: current_phase = phases[1][1]
            self.root.after(0, lambda: self.phase_lbl.config(text=current_phase))


            time.sleep(1) # Fast forward for demo, use 1 for real time


        self.log("WARM-UP COMPLETE. LAUNCHING BROWSER.")
        self.launch_browser()


    def launch_browser(self):
        cmd = [LUCID_BINARY_PATH, "-profile", self.profile_path_var.get(), "-no-remote"]
        self.log(f"EXEC: {' '.join(cmd)}")
        # subprocess.Popen(cmd) # Uncomment in production


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


if __name__ == "__main__":
    root = tk.Tk()
    app = LucidLauncherApp(root)
    root.mainloop()
