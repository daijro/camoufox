#!/usr/bin/env python3
"""
Generate the tables and constants of UcrtMathPow.c and UcrtMathTrig.c.

    python3 scripts/gen-ucrt-math-tables.py           # write the two headers
    python3 scripts/gen-ucrt-math-tables.py --check   # fail if they are stale

Every value is computed here from its definition (1/F, ln(2F), 2^(j/64), the
bits of 2/pi, splits of ln 2 and pi/2) at a few hundred digits, then rounded to
a double by the rule that table uses. The rules reproduce AMD LibM's tables
(aocl-libm-ose, src/isa/avx/gas/pow.S and remainder_piby2_new.S) bit for bit:
a head is the value truncated to a short significand, and its tail is the
rest, truncated or rounded to nearest as AMD's are. The minimax polynomial
coefficients are not derivable this way; they stay in the C files, cited.

Standard library only. Each value is computed at two precisions, and a result
that depends on the precision fails rather than being written.
"""

import argparse
import sys
from decimal import Decimal, getcontext, localcontext
from fractions import Fraction
from math import factorial
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "additions" / "js" / "src" / "builtin"
PRECISIONS = (420, 460)  # decimal digits; 2/pi needs about 1200 bits


def atan_inv(n):
    """atan(1/n) at the current decimal precision."""
    x = Decimal(1) / n
    x2 = x * x
    term = total = x
    k = 1
    tiny = Decimal(10) ** -(getcontext().prec + 5)
    while abs(term) > tiny:
        term *= -x2
        k += 2
        total += term / k
    return total


def constants(digits):
    """pi, ln and exp at `digits` decimal digits, as exact fractions."""
    def at_precision(f):
        def g(*args):
            with localcontext() as ctx:
                ctx.prec = digits
                return Fraction(f(*args))
        return g

    as_decimal = lambda q: Decimal(q.numerator) / q.denominator
    return {
        "pi": at_precision(lambda: 16 * atan_inv(5) - 4 * atan_inv(239))(),  # Machin
        "ln": at_precision(lambda q: as_decimal(q).ln()),
        "exp": at_precision(lambda q: as_decimal(q).exp()),
    }


def to_double(v, bits=53, mode="nearest"):
    """IEEE double bits of v cut to `bits` significant bits: round to nearest
    (ties to even) or truncate toward zero. Normal numbers and zero only."""
    if v == 0:
        return 0
    sign = 1 << 63 if v < 0 else 0
    v = abs(v)
    e = v.numerator.bit_length() - v.denominator.bit_length()
    if v >= Fraction(2) ** (e + 1):
        e += 1
    elif v < Fraction(2) ** e:
        e -= 1
    scaled = v / Fraction(2) ** (e - bits + 1)
    n, rest = divmod(scaled.numerator, scaled.denominator)
    if mode == "nearest" and (2 * rest > scaled.denominator or (2 * rest == scaled.denominator and n & 1)):
        n += 1
    if n >> bits:
        n >>= 1
        e += 1
    assert -1022 <= e <= 1023, "subnormal or overflow"
    return sign | (e + 1023) << 52 | (n << (53 - bits)) & ((1 << 52) - 1)


def value(b):
    """The exact value of double bits b (normal or zero)."""
    if b & ~(1 << 63) == 0:
        return Fraction(0)
    v = Fraction((b & ((1 << 52) - 1)) | 1 << 52) * Fraction(2) ** (((b >> 52) & 0x7FF) - 1075)
    return -v if b >> 63 else v


def split(v, head_bits, tail_mode):
    """A head of `head_bits` significant bits (truncated) and the rest."""
    head = to_double(v, head_bits, "truncate")
    return head, to_double(v - value(head), 53, tail_mode)


def pow_tables(c):
    ln2 = c["ln"](Fraction(2))
    # ln 2: a 24-bit head and a truncated tail.
    ln2_head, ln2_tail = split(ln2, 24, "truncate")
    t = {"LN2_HEAD": ln2_head, "LN2_TAIL": ln2_tail}

    # log(x) = e*ln2 + ln(2F) + ln(1 - r), F = (256 + i)/512, r = (F - Y)/F.
    # 1/F's head has 9 bits so that (F - Y) * head, at most 44 + 9 bits, is
    # exact; its tail is rounded to nearest. ln(2F) is truncated to 25 bits
    # and its tail truncated; the last entry, ln 2, is the ln 2 pair above.
    inv = [split(Fraction(512, 256 + i), 9, "nearest") for i in range(257)]
    log = [split(c["ln"](Fraction(256 + i, 256)), 25, "truncate") for i in range(256)]
    log.append((ln2_head, ln2_tail))
    t["INV_HEAD"], t["INV_TAIL"] = zip(*inv)
    t["LOG_HEAD"], t["LOG_TAIL"] = zip(*log)

    # exp(w) = 2^m * 2^(j/64) * exp(rr), n = 64m + j = round(w * 64/ln2), and
    # rr = w - n*ln2/64. ln2/64's tail is stored negated, since rr adds it.
    head, tail = split(ln2 / 64, 25, "truncate")
    t["SIXTY4_BY_LN2"] = to_double(64 / ln2)
    t["LN2_BY_64_HEAD"], t["LN2_BY_64_TAIL"] = head, tail ^ 1 << 63
    exp = [split(c["exp"](Fraction(j, 64) * ln2), 25, "truncate") for j in range(64)]
    t["EXP_HEAD"], t["EXP_TAIL"] = zip(*exp)

    # Below this w = y*ln(x) the result is under 1.5 * 2^-1074, so it rounds to
    # the smallest subnormal.
    t["DENORM_W_LIM"] = to_double(c["ln"](Fraction(3, 2)) - 1074 * ln2)

    # ln(1 - r) = -(r + r^2/2 + ... + r^7/7) and exp(rr) - 1 = rr + ... + rr^6/6!.
    # AMD's 1/7 is two units in the last place above the nearest double; it is
    # kept as published (the recorded outputs agree with either).
    log_c = [to_double(Fraction(1, k)) for k in range(2, 8)]
    log_c[-1] += 2
    t["LOG_C"] = log_c
    t["EXP_C"] = [to_double(Fraction(1, factorial(k))) for k in range(6, 0, -1)]
    return t


def trig_tables(c):
    pi = c["pi"]
    t = {"K_PIBY4": to_double(pi / 4), "K_TWOBYPI": to_double(2 / pi), "K_SIXTH": to_double(Fraction(1, 6))}
    t["K_POINT68"] = to_double(Fraction(68, 100))
    t["K_PIBY4_LO"] = to_double(pi / 4 - value(t["K_PIBY4"]), 53, "truncate")

    # |x| < 2e7: x - n*pi/2 with pi/2 as three parts, the nearest double, then
    # the rest cut to 43 bits, then what remains of that cut to 47 bits.
    p1 = to_double(pi / 2)
    p2 = to_double(pi / 2 - value(p1), 43, "truncate")
    p3 = to_double(pi / 2 - value(p1) - value(p2), 47, "truncate")
    t.update({"K_PIBY2_1": p1, "K_PIBY2_2": p2, "K_PIBY2_3": p3})

    # Payne-Hanek: the reduced argument times pi/2, with pi/2 as a 25-bit
    # head, whose product with the argument's 26-bit head is exact, a second
    # 25-bit part and the truncated rest.
    h = to_double(pi / 2, 25, "truncate")
    m = to_double(pi / 2 - value(h), 25, "truncate")
    t.update({"K_PIBY2_H": h, "K_PIBY2_M": m,
              "K_PIBY2_L": to_double(pi / 2 - value(h) - value(m), 53, "truncate")})

    # The first 1197 fraction bits of 2/pi, scaled by 2^1202 into a
    # little-endian integer whose top byte is 2 (4 * 2/pi = 2.54...), then
    # seven zero bytes, as AMD's table is. reduce_large reads bytes 7 to 154.
    n = int(2 / pi * 2**1197) << 5
    t["TWOBYPI"] = list(n.to_bytes(151, "little")) + [0] * 7
    return t


def array(name, values, ctype="uint64_t", per_line=4, fmt="0x{:016x}ULL"):
    rows = [", ".join(fmt.format(v) for v in values[i:i + per_line]) + ","
            for i in range(0, len(values), per_line)]
    return f"static const {ctype} {name}[{len(values)}] = {{\n" + "\n".join("    " + r for r in rows) + "\n};\n"


HEADER = """/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Generated by browser/scripts/gen-ucrt-math-tables.py; do not edit. */

#ifndef {guard}
#define {guard}

#include <stdint.h>

"""


def render_pow(t):
    out = HEADER.format(guard="builtin_UcrtMathPowTables_h")
    for name in ("LN2_HEAD", "LN2_TAIL", "SIXTY4_BY_LN2", "LN2_BY_64_HEAD", "LN2_BY_64_TAIL", "DENORM_W_LIM"):
        out += f"static const uint64_t {name} = 0x{t[name]:016x}ULL;\n"
    out += "\n/* 1/2 ... 1/7 */\n" + array("LOG_C", t["LOG_C"], per_line=3)
    out += "/* 1/6! ... 1/1! */\n" + array("EXP_C", t["EXP_C"], per_line=3)
    for name in ("INV_HEAD", "INV_TAIL", "LOG_HEAD", "LOG_TAIL", "EXP_HEAD", "EXP_TAIL"):
        out += array(name, list(t[name]))
    return out + "\n#endif /* builtin_UcrtMathPowTables_h */\n"


def render_trig(t):
    out = HEADER.format(guard="builtin_UcrtMathTrigTables_h")
    for name in ("K_PIBY4", "K_PIBY4_LO", "K_TWOBYPI", "K_PIBY2_1", "K_PIBY2_2", "K_PIBY2_3",
                 "K_PIBY2_H", "K_PIBY2_M", "K_PIBY2_L", "K_SIXTH", "K_POINT68"):
        out += f"#define {name} 0x{t[name]:016x}ULL\n"
    out += "\n" + array("TWOBYPI", t["TWOBYPI"], "uint8_t", 12, "0x{:02x}")
    return out + "\n#endif /* builtin_UcrtMathTrigTables_h */\n"


def generate():
    """{file name: contents}, identical at every precision in PRECISIONS."""
    results = []
    for digits in PRECISIONS:
        c = constants(digits)
        results.append({"UcrtMathPowTables.h": render_pow(pow_tables(c)),
                        "UcrtMathTrigTables.h": render_trig(trig_tables(c))})
    if any(r != results[0] for r in results):
        sys.exit("a table depends on the working precision; raise PRECISIONS")
    return results[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if a header differs from the generated one")
    args = parser.parse_args()
    stale = []
    for name, text in generate().items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.write_text(text)
    if stale:
        sys.exit(f"stale: {', '.join(stale)}; run browser/scripts/gen-ucrt-math-tables.py")


if __name__ == "__main__":
    main()
