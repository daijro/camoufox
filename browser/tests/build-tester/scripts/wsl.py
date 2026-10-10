"""
WSL (Windows Subsystem for Linux) detection helpers.
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

