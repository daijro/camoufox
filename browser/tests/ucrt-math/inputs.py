"""Inputs for the Windows CRT math reference, identical on every platform.

record.py (on Windows) and check.py (anywhere) both build their inputs here, so
the reference file holds only results. Everything is integer arithmetic or a
single IEEE + - * /, never libm: math.log on Windows and Linux can differ in the
last bit, and an input built with it would silently differ between the two.
"""

import struct

MASK64 = (1 << 64) - 1


def dbl(b):
    return struct.unpack("<d", struct.pack("<Q", b & MASK64))[0]


def bits(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def finite(b):
    return (b >> 52) & 0x7FF != 0x7FF


class SplitMix64:
    def __init__(self, seed):
        self.state = seed & MASK64

    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def unit(self):
        return (self.next() >> 11) * (1.0 / (1 << 53))

    def uniform(self, lo, hi):
        return lo + (hi - lo) * self.unit()


PI = 3.141592653589793


def p2(e):
    """2**e built from bits: Python's float ** calls the platform's pow()."""
    if e < -1022:
        return dbl(1 << (e + 1074))
    return dbl((e + 1023) << 52)


def p10(e):
    x = 1.0
    for _ in range(e):
        x *= 10.0
    return x


def _around(out, x, n):
    q = bits(abs(x))
    for k in range(-n, n + 1):
        for sign in (0, 1 << 63):
            b = (q + k) | sign
            if finite(b):
                out.append(b)


def trig_inputs():
    """Bit patterns for sin/cos/tan: random, then every branch edge."""
    rng = SplitMix64(152)
    out = []
    while len(out) < 8000:
        b = rng.next()
        if finite(b):
            out.append(b)
    out += [bits(rng.uniform(-10.0, 10.0)) for _ in range(8000)]
    out += [bits(rng.uniform(-1e6, 1e6)) for _ in range(4000)]
    # Branch thresholds of the CRT: pi/4, tan's 0.68, the 2e7 switch to
    # Payne-Hanek, and the 2^-27 / 2^-13 small-argument cutoffs.
    for t in (PI / 4, 0.68, 2e7, p2(-27), p2(-13), 1.0, 0.5):
        _around(out, t, 40)
    for k in range(1, 300):
        _around(out, k * PI / 2, 3)
        _around(out, k * PI / 4, 2)
    for e in range(3, 300, 7):
        _around(out, p10(e) * PI / 2, 3)
    # Arguments known to be hardest for argument reduction, and the extremes.
    for hard in (6381956970095103 * p2(797), 5.319372648326541e255, 1e22, p2(1023),
                 1.7976931348623157e308, 3.4e38, p2(1000)):
        _around(out, hard, 10)
    for e in range(-1074, 1024, 3):
        _around(out, p2(e), 1)
    return out


def _log2_rough(x):
    """A deterministic stand-in for log2 on [1, 4): only + - * /, no libm."""
    e = 0
    while x >= 2.0:
        x *= 0.5
        e += 1
    t = (x - 1.0) / (x + 1.0)
    t2 = t * t
    return e + 2.8853900817779268 * t * (1.0 + t2 / 3.0 + t2 * t2 / 5.0 + t2 * t2 * t2 / 7.0)


SPECIAL = [0, 1 << 63, 0x3FF0000000000000, 0xBFF0000000000000, 0x7FF0000000000000,
           0xFFF0000000000000, 0x7FF8000000000000, 0xFFF8000000000000, 1, 0x8000000000000001,
           0x000FFFFFFFFFFFFF, 0x800FFFFFFFFFFFFF, 0x0010000000000000, 0x7FEFFFFFFFFFFFFF,
           0xFFEFFFFFFFFFFFFF]
SPECIAL_NUMS = [0.5, -0.5, 2.0, -2.0, 3.0, -3.0, 0.25, 1e-300, -1e-300, 1e300, -1e300, 10.0, -10.0,
                1.0000000000000002, 0.9999999999999999, -1.0000000000000002, 1e-310, -1e-310, 2.5,
                -2.5, p2(53), -p2(53), p2(53) + 2, p2(54) + 2, p2(63), -p2(63),
                p2(64), 1e20, -1e20, 1023.0, 1024.0, -1022.0, -1074.0, -1075.0, -1076.0, 1e-17,
                1e-20, -1e-20, 7.0, -7.0, 0.1, -0.1]


def pow_inputs():
    """(x, y) bit-pattern pairs for pow."""
    rng = SplitMix64(1520)
    out = []
    for _ in range(6000):
        out.append((bits(rng.uniform(0.0, 100.0)), bits(rng.uniform(-50.0, 50.0))))
    while len(out) < 9000:
        b = rng.next()
        if finite(b):
            out.append((b, bits(rng.uniform(-4.0, 4.0))))
    vals = SPECIAL + [bits(v) for v in SPECIAL_NUMS]
    out += [(a, b) for a in vals for b in vals]
    # Results near overflow, underflow and the subnormal range.
    for _ in range(12000):
        x = rng.uniform(1.0001, 3.0)
        if rng.next() & 1:
            x = -x
        y = rng.uniform(-1080.0, 1030.0) / _log2_rough(abs(x))
        if rng.unit() < 0.3:
            y = float(int(y))
        out.append((bits(x), bits(y)))
    for _ in range(3000):
        out.append((rng.next() >> 12 | (rng.next() & (1 << 63)), bits(rng.uniform(-3.0, 3.0))))
    return out
