#!/usr/bin/env python3
"""
Generate the tables and constants of UcrtMathPow.c and UcrtMathTrig.c.

    python3 scripts/gen-ucrt-math-tables.py           # write the two headers
    python3 scripts/gen-ucrt-math-tables.py --check   # fail if they are stale

Every value is computed here from its definition at a few hundred digits,
then rounded to a double by the rule that table uses:

- pow: the tables of Arm's optimized-routines pow (math/pow_log_data.c and
  math/exp_data.c, MIT OR Apache-2.0 WITH LLVM-exception), by the rules those
  files state: for log, 1/c at each of 128 subintervals' centers with few bits,
  log(c) rounded to a multiple of 2^-43 and the rest; for exp, 2^(k/256) as a
  double and a relative correction.
- sin/cos/tan: the bits of 2/pi and the splits of pi/2 and pi/4 in AMD LibM
  (aocl-libm-ose, remainder_piby2_new.S): a head is the value truncated to a
  short significand, and its tail is the rest, truncated or rounded to nearest
  as AMD's are.

The minimax polynomial coefficients are not derivable this way; they stay in
the C files, cited.

Standard library only. Each value is computed at two precisions, and a result
that depends on the precision fails rather than being written.
"""

import argparse
import sys
from decimal import Decimal, getcontext, localcontext
from fractions import Fraction
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


POW_LOG_BITS = 7            # 128 subintervals for log
POW_LOG_OFF = 0x3FE6955500000000
EXP_BITS = 8                # 256 entries for exp


def rint(q):
    """q rounded to the nearest integer, ties to even."""
    n, r = divmod(q.numerator, q.denominator)
    return n + (2 * r > q.denominator or (2 * r == q.denominator and n & 1))


def pow_tables(c):
    """Arm's optimized-routines pow: log with 128 subintervals, exp with 256.
    The rules are the ones its pow_log_data.c and exp_data.c state."""
    ln2 = c["ln"](Fraction(2))
    t = {}
    # log(x) = k ln2 + log(c) + log1p(z/c - 1), z in [OFF, 2 OFF) split into N
    # subintervals. 1/c has few bits, so z/c - 1 is exact: 1/c is the
    # subinterval's center rounded to a multiple of 1/N (1/2N above 1). log(c)
    # is rounded to a multiple of 2^-43, as ln2hi is, so k ln2hi + logc is
    # exact; logctail is the rest.
    n = 1 << POW_LOG_BITS
    invc, logc, logctail = [], [], []
    for i in range(n):
        center = value(POW_LOG_OFF + (i << (52 - POW_LOG_BITS)) + (1 << (51 - POW_LOG_BITS)))
        ic = Fraction(rint(n / center), n) if center < 1 else Fraction(rint(2 * n / center), 2 * n)
        lc = -c["ln"](ic)
        lc_head = Fraction(rint(lc * 2**43), 2**43)
        invc.append(to_double(ic))
        logc.append(to_double(lc_head))
        logctail.append(to_double(lc - lc_head))
    t["POW_LOG_INVC"], t["POW_LOG_LOGC"], t["POW_LOG_LOGCTAIL"] = invc, logc, logctail
    ln2hi = Fraction(rint(ln2 * 2**43), 2**43)
    t["LN2HI"], t["LN2LO"] = to_double(ln2hi), to_double(ln2 - ln2hi)

    # exp(x) = 2^(k/N) exp(r): 2^(k/N) ~= H[k] (1 + T[k]), stored as T[k] and
    # H[k] with k/N taken out of its exponent. ln2/N is a 35-bit head and the
    # rest, both negated; N/ln2 is rounded once.
    ne = 1 << EXP_BITS
    tab = []
    for k in range(ne):
        v = c["exp"](Fraction(k, ne) * ln2)
        h = to_double(v)
        tab += [to_double((v - value(h)) / value(h)), (h - (k << 52) // ne) % (1 << 64)]
    t["EXP_TAB"] = tab
    hi = to_double(ln2 / ne, 35, "nearest")
    t["INVLN2N"] = to_double(ne / ln2)
    t["NEGLN2HIN"] = hi ^ 1 << 63
    t["NEGLN2LON"] = to_double(-(ln2 / ne - value(hi)))
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
    out += f"#define POW_LOG_TABLE_BITS {POW_LOG_BITS}\n#define EXP_TABLE_BITS {EXP_BITS}\n\n"
    for name in ("LN2HI", "LN2LO", "INVLN2N", "NEGLN2HIN", "NEGLN2LON"):
        out += f"static const uint64_t {name} = 0x{t[name]:016x}ULL;\n"
    out += "\n/* log: 1/c, log(c) to a multiple of 2^-43, and the rest of log(c). */\n"
    for name in ("POW_LOG_INVC", "POW_LOG_LOGC", "POW_LOG_LOGCTAIL"):
        out += array(name, t[name])
    out += "/* exp: T[k], then H[k] - (k << 52)/N, for 2^(k/N) ~= H[k] (1 + T[k]). */\n"
    out += array("EXP_TAB", t["EXP_TAB"])
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
