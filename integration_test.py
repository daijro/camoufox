"""Phase 5 Integration Test"""
from lucid_launcher import LucidLauncherApp
import tkinter as tk

# Initialize
root = tk.Tk()
app = LucidLauncherApp(root)

# Test 1: Proxy Validation
print("=== TEST 1: Proxy Validation ===")
app.proxy_var.set("socks5://127.0.0.1:1080")
app.identity_text.insert("1.0", '{"zip":"90210"}')
app.test_proxy()

# Test 2: Profile Compilation
print("\n=== TEST 2: Profile Compilation ===")
app.compile_profile()

# Test 3: Aging Slider
print("\n=== TEST 3: Aging Slider ===")
app.aging_days.set(30)
print(f"Aging days value: {app.aging_days.get()}")

print("\nAll tests completed. Launch UI to verify visual components.")
