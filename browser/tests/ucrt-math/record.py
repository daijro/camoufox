"""Record the Windows CRT's sin/cos/tan/pow results for inputs.py (run on Windows).

    py browser/tests/ucrt-math/record.py

Calls ucrtbase.dll with its FMA3 code path forced on (the path every CPU since
Haswell / Piledriver takes, and the one UcrtMath*.c reproduces) and writes
expected.u64.xz plus provenance.json. Results are passed back as raw bits, so a
NaN payload survives.
"""

import ctypes
import hashlib
import json
import lzma
import platform
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inputs import dbl, pow_inputs, trig_inputs  # noqa: E402

HERE = Path(__file__).resolve().parent


def inputs_digest(trig, pw):
    flat = trig + [v for pair in pw for v in pair]
    return hashlib.sha256(struct.pack(f"<{len(flat)}Q", *flat)).hexdigest()


def main():
    dll_path = Path(r"C:\Windows\System32\ucrtbase.dll")
    crt = ctypes.CDLL(str(dll_path))
    crt._set_FMA3_enable.argtypes = [ctypes.c_int]
    crt._get_FMA3_enable.restype = ctypes.c_int
    if not crt._set_FMA3_enable(1) or crt._get_FMA3_enable() != 1:
        sys.exit("this CPU has no FMA3; the reference must come from the FMA3 path")

    unary = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double)
    binary = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double, ctypes.c_double)
    addr = lambda name: ctypes.cast(getattr(crt, name), ctypes.c_void_p).value
    fns = {name: unary(addr(name)) for name in ("sin", "cos", "tan")}
    pow_fn = binary(addr("pow"))
    as_bits = lambda x: struct.unpack("<Q", struct.pack("<d", x))[0]

    trig, pw = trig_inputs(), pow_inputs()
    out = []
    for name in ("sin", "cos", "tan"):
        out += [as_bits(fns[name](dbl(b))) for b in trig]
    out += [as_bits(pow_fn(dbl(a), dbl(b))) for a, b in pw]
    (HERE / "expected.u64.xz").write_bytes(lzma.compress(struct.pack(f"<{len(out)}Q", *out)))

    ver = ctypes.windll.version
    size = ver.GetFileVersionInfoSizeW(str(dll_path), None)
    buf = ctypes.create_string_buffer(size)
    ver.GetFileVersionInfoW(str(dll_path), 0, size, buf)
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length))
    ms, ls = struct.unpack_from("<II", ctypes.string_at(ptr.value + 8, 8))
    version = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    json.dump({
        "ucrtbase": version,
        "ucrtbase_sha256": hashlib.sha256(dll_path.read_bytes()).hexdigest(),
        "windows": platform.version(),
        "fma3": True,
        "inputs_sha256": inputs_digest(trig, pw),
        "trig_inputs": len(trig),
        "pow_inputs": len(pw),
    }, open(HERE / "provenance.json", "w"), indent=2)
    print(f"{len(trig)} trig and {len(pw)} pow inputs recorded from ucrtbase {version}")


if __name__ == "__main__":
    main()
