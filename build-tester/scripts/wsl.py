"""
WSL (Windows Subsystem for Linux) detection and path conversion helpers.
Used when running a Linux Camoufox binary from a Windows host.
"""

import re
import subprocess


def is_elf_binary(file_path: str) -> bool:
    try:
        with open(file_path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except Exception:
        return False


def get_windows_host_ip() -> str:
    try:
        result = subprocess.run(
            ["wsl", "bash", "-lc", "ip route show default"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
        return m.group(1) if m else "localhost"
    except Exception:
        return "localhost"


def windows_to_wsl_path(win_path: str) -> str:
    wsl_m = re.match(r"^[\\\/]{2}(?:wsl\$|wsl\.localhost)[\\\/][^\\\/]+[\\\/](.*)", win_path, re.IGNORECASE)
    if wsl_m:
        return "/" + wsl_m.group(1).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):\\", win_path)
    if not m:
        return win_path.replace("\\", "/")
    return f"/mnt/{m.group(1).lower()}/{win_path[3:].replace(chr(92), '/')}"
