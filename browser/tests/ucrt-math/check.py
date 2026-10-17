"""Check browser/additions/js/src/builtin/UcrtMath*.c bit for bit against the Windows CRT.

    python3 browser/tests/ucrt-math/check.py

Builds the two C files on their own (no Firefox needed), the way js/src does:
-ffp-contract=off, so each operation rounds exactly once, as the CRT's
instructions do. Then compares every result with expected.u64.xz, recorded from
ucrtbase.dll by record.py. Any difference fails.
"""

import ctypes
import json
import lzma
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

SRC = HERE.parents[1] / "additions" / "js" / "src" / "builtin"
CFLAGS = ["-O2", "-fPIC", "-shared", "-ffp-contract=off", "-Wall", "-Wextra", "-Werror"]


def build(tmp):
    lib = Path(tmp) / "libucrtmath.so"
    cc = os.environ.get("CC", "cc")
    subprocess.run([cc, *CFLAGS, "-I", str(SRC.parent), "-o", str(lib), str(SRC / "UcrtMathTrig.c"),
                    str(SRC / "UcrtMathPow.c"), "-lm"], check=True)
    return ctypes.CDLL(str(lib))


def main():
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
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
