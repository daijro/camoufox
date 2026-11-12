#!/usr/bin/env python3
"""
Check SkCpuEstimates.h with the shipped tables against real CPUs.

    python3 browser/tests/cpu-estimates/check.py

On an Intel or AMD host, the emulation of the host's vendor must give the
native RCPPS/RSQRTPS bits for every one of the 2^32 inputs. For both vendors,
the emulation's hashes over all inputs must equal the native hashes recorded on
that vendor's CPU (provenance.json), so one host checks the other vendor too.
A few minutes on one core.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import PROVENANCE, VENDORS, build  # noqa: E402


def main():
    exe = build(tables=True)
    prov = json.loads(PROVENANCE.read_text())
    failed = False
    for index, vendor in VENDORS.items():
        out = subprocess.run([exe, "hash", index], capture_output=True, text=True, check=True).stdout.split()
        got = dict(zip(out[::2], out[1::2]))
        ok = got == prov[vendor]["hashes"]
        failed |= not ok
        print(f"{vendor}: emulated {got}, recorded {prov[vendor]['hashes']}: {'ok' if ok else 'MISMATCH'}")
    host = subprocess.run([exe, "vendor"], capture_output=True, text=True, check=True).stdout.strip()
    if host in VENDORS:
        run = subprocess.run([exe, "check", host], capture_output=True, text=True)
        print(f"host ({VENDORS[host]}) native vs emulated:\n{run.stdout.strip()}")
        failed |= run.returncode != 0
    else:
        print("host is neither Intel nor AMD: native comparison skipped")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
