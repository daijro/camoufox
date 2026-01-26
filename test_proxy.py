from lucid_launcher import LucidLauncherApp
import tkinter as tk

# Create minimal window
root = tk.Tk()
app = LucidLauncherApp(root)

# Test with sample proxy
app.proxy_var.set("socks5://127.0.0.1:1080")
app.identity_text.insert("1.0", '{"zip":"90210"}')
app.test_proxy()
