#!/usr/bin/env python3
"""
Record this CPU's RCPPS/RSQRTPS tables for general.cpu_identity (Intel, AMD).

    python3 browser/tests/cpu-estimates/record.py
    python3 browser/scripts/gen-cpu-estimate-tables.py

Run once on an Intel and once on an AMD x86-64 machine. The table goes to
recorded/<vendor>.txt and the CPU and the native instructions' hashes over all
2^32 inputs to provenance.json; check.py compares the emulation with those
hashes. Any generation of a vendor gives the same table (SkCpuEstimates.h), so
a new recording only adds a CPU to that vendor's list, and a recording that
disagrees with the stored table fails instead of replacing it.

--dump takes the output of `estimates dump` run on another machine (build it
with `cc -O2 -static -I<opts> estimates.c`), with --cpu naming that CPU.
"""

import argparse
import datetime
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OPTS = ROOT / "additions" / "gfx" / "skia" / "skia" / "src" / "opts"
RECORDED = HERE / "recorded"
PROVENANCE = HERE / "provenance.json"
VENDORS = {"1": "intel", "2": "amd"}
ENTRIES = 3 * 4096


def build(tables=False):
    out = Path(tempfile.mkdtemp(prefix="cpu-estimates-")) / "estimates"
    cmd = ["cc", "-O2", "-std=c99", "-Wall", "-Werror", f"-I{OPTS}", str(HERE / "estimates.c"), "-o", str(out)]
    if tables:
        cmd.insert(1, "-DTABLES")
    subprocess.run(cmd, check=True)
    return out


def host_cpu():
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


def parse_dump(text):
    lines = text.split()
    table, hashes = lines[:ENTRIES], dict(zip(lines[ENTRIES::2], lines[ENTRIES + 1::2]))
    if len(table) != ENTRIES or set(hashes) != {"rcp", "rsqrt"}:
        sys.exit("not an `estimates dump` output")
    return table, hashes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", type=Path, help="`estimates dump` output from another machine")
    ap.add_argument("--cpu", help="that machine's CPU, as its OS names it")
    ap.add_argument("--vendor", choices=sorted(VENDORS.values()), help="that machine's CPU vendor")
    args = ap.parse_args()

    if args.dump:
        if not (args.cpu and args.vendor):
            sys.exit("--dump needs --cpu and --vendor")
        text, cpu, vendor = args.dump.read_text(), args.cpu, args.vendor
    else:
        exe = build()
        vendor = VENDORS.get(subprocess.run([exe, "vendor"], capture_output=True, text=True, check=True).stdout.strip())
        if not vendor:
            sys.exit("this CPU is neither Intel nor AMD")
        text, cpu = subprocess.run([exe, "dump"], capture_output=True, text=True, check=True).stdout, host_cpu()
    table, hashes = parse_dump(text)

    RECORDED.mkdir(exist_ok=True)
    path = RECORDED / f"{vendor}.txt"
    if path.exists() and path.read_text().split() != table:
        sys.exit(f"{cpu} gives another {vendor} table than {path.name}: the per-vendor premise is wrong")
    path.write_text("\n".join(table) + "\n")

    prov = json.loads(PROVENANCE.read_text()) if PROVENANCE.exists() else {}
    entry = prov.setdefault(vendor, {"hashes": hashes, "cpus": []})
    if entry["hashes"] != hashes:
        sys.exit(f"{cpu}'s native hashes differ from the recorded {vendor} ones")
    if not any(c["cpu"] == cpu for c in entry["cpus"]):
        entry["cpus"].append({"cpu": cpu, "recorded": datetime.date.today().isoformat()})
    PROVENANCE.write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n")
    print(f"{vendor}: {cpu}, rcp {hashes['rcp']} rsqrt {hashes['rsqrt']}")


if __name__ == "__main__":
    main()
