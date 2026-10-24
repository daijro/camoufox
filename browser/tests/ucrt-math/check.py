"""Check browser/additions/js/src/builtin/UcrtMath*.c bit for bit against the Windows CRT.

    python3 browser/tests/ucrt-math/check.py

First checks that the tables in UcrtMath*Tables.h are what
browser/scripts/gen-ucrt-math-tables.py generates. Then builds the two C files
on their own (no Firefox needed), the way js/src does: -ffp-contract=off, so
each operation rounds exactly once, as the CRT's instructions do. Then compares
every result with expected.u64.xz, recorded from ucrtbase.dll by record.py. Any
difference fails.

Last, it checks the stock Windows Firefox reference the windows-crt-math guard
uses (record_firefox.py): that it holds the inputs record_firefox.py samples,
in the shape the guard reads, and that wherever Firefox calls the CRT it agrees
with expected.u64.xz, so the two recordings cannot drift apart.
"""

import ctypes
import json
import lzma
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from inputs import dbl, pow_inputs, trig_inputs  # noqa: E402
from record import inputs_digest  # noqa: E402
from record_firefox import OUT as FIREFOX_REFERENCE, sample  # noqa: E402

SRC = HERE.parents[1] / "additions" / "js" / "src" / "builtin"
GENERATOR = HERE.parents[1] / "scripts" / "gen-ucrt-math-tables.py"
CFLAGS = ["-O2", "-fPIC", "-shared", "-ffp-contract=off", "-Wall", "-Wextra", "-Werror"]


def build(tmp):
    lib = Path(tmp) / "libucrtmath.so"
    cc = os.environ.get("CC", "cc")
    subprocess.run([cc, *CFLAGS, "-I", str(SRC.parent), "-o", str(lib), str(SRC / "UcrtMathTrig.c"),
                    str(SRC / "UcrtMathPow.c"), "-lm"], check=True)
    return ctypes.CDLL(str(lib))


def main():
    subprocess.run([sys.executable, str(GENERATOR), "--check"], check=True)
    provenance = json.loads((HERE / "provenance.json").read_text())
    trig, pw = trig_inputs(), pow_inputs()
    if inputs_digest(trig, pw) != provenance["inputs_sha256"]:
        sys.exit("inputs.py no longer produces the inputs expected.u64.xz was recorded for; "
                 "rerun record.py on Windows")
    raw = lzma.decompress((HERE / "expected.u64.xz").read_bytes())
    expected = struct.unpack(f"<{len(raw) // 8}Q", raw)

    with tempfile.TemporaryDirectory() as tmp:
        lib = build(tmp)
        for name in ("ucrt_sin", "ucrt_cos", "ucrt_tan"):
            getattr(lib, name).restype = ctypes.c_double
            getattr(lib, name).argtypes = [ctypes.c_double]
        lib.ucrt_pow.restype = ctypes.c_double
        lib.ucrt_pow.argtypes = [ctypes.c_double, ctypes.c_double]
        as_bits = lambda x: struct.unpack("<Q", struct.pack("<d", x))[0]

        failed = False
        pos = 0
        for name in ("sin", "cos", "tan", "pow"):
            fn = getattr(lib, "ucrt_" + name)
            args = [(dbl(a), dbl(b)) for a, b in pw] if name == "pow" else [(dbl(b),) for b in trig]
            want = expected[pos:pos + len(args)]
            pos += len(args)
            bad = [(a, g, w) for a, w in zip(args, want) if (g := as_bits(fn(*a))) != w]
            print(f"{name}: {len(args) - len(bad)}/{len(args)} bit-exact "
                  f"(ucrtbase {provenance['ucrtbase']})")
            for a, g, w in bad[:10]:
                print("   ", [x.hex() for x in a], f"got {g:016x} want {w:016x}")
            failed |= bool(bad)
    failed |= not firefox_reference_agrees(trig, pw, expected)
    sys.exit(1 if failed else 0)


def crt_path(x, y):
    """Whether SpiderMonkey's pow (ecmaPow) passes x, y to the CRT, rather than
    powi, its sqrt cases or its ECMAScript special cases; a page's NaN is
    always the canonical one."""
    if x != x or y != y or y == 0:
        return False
    if math.isfinite(y) and y == int(y) and abs(y) < 2**31:
        return False
    if not math.isfinite(y) and abs(x) == 1:
        return False
    return not (math.isfinite(x) and x != 0 and abs(y) == 0.5)


def firefox_reference_agrees(trig, pw, expected):
    ref = json.loads(FIREFOX_REFERENCE.read_text())
    problems = []
    if ref["input"] != sample():
        problems.append("its inputs are not what record_firefox.sample() gives; re-record it")
    if set(ref["expected"]) != {"results", "constants"}:
        problems.append(f"it has {sorted(ref['expected'])}, the guard reads results and constants")
    if not problems:
        results = ref["expected"]["results"]
        crt = {name: dict(zip(trig, expected[k * len(trig):(k + 1) * len(trig)]))
               for k, name in enumerate(("sin", "cos", "tan"))}
        crt["pow"] = dict(zip(pw, expected[3 * len(trig):]))
        for name in ("sin", "cos", "tan"):
            for h, got in zip(ref["input"]["trig"], results[name]):
                b = int(h, 16)
                if dbl(b) == dbl(b) and int(got, 16) != crt[name][b]:
                    problems.append(f"{name}({h}): Firefox {got}, ucrtbase {crt[name][b]:016x}")
        for (hx, hy), got in zip(ref["input"]["pow"], results["pow"]):
            a, b = int(hx, 16), int(hy, 16)
            if crt_path(dbl(a), dbl(b)) and int(got, 16) != crt["pow"][(a, b)]:
                problems.append(f"pow({hx}, {hy}): Firefox {got}, ucrtbase {crt['pow'][(a, b)]:016x}")
    print(f"Firefox reference ({ref['firefox']}): "
          + ("agrees with ucrtbase" if not problems else f"{len(problems)} problems"))
    for p in problems[:10]:
        print("   ", p)
    return not problems


if __name__ == "__main__":
    main()
