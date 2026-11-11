/* armest.h - bit-exact portable C model of AArch64 FRECPE/FRSQRTE/FRECPS/FRSQRTS
 * (single precision), per the Arm ARM pseudocode FPRecipEstimate, FPRSqrtEstimate,
 * RecipEstimate, RecipSqrtEstimate, FPRecipStepFused, FPRSqrtStepFused, with
 * FPCR = FZ 0, DN 0, AH 0, RMode RNE (Linux/macOS user default; no FEAT_RPRES).
 * Integer-only arithmetic: no FP environment, intrinsics or libm dependence.
 * Tables generated from the RecipEstimate / RecipSqrtEstimate loops (gen.py). */
#ifndef ARMEST_H
#define ARMEST_H
#include <stdint.h>
#include <string.h>

static const uint8_t armest_recip_tab[256] = {
  255,253,251,249,247,245,243,241,240,238,236,234,232,230,229,227,
  225,223,221,220,218,216,215,213,211,210,208,206,205,203,201,200,
  198,197,195,194,192,191,189,188,186,185,183,182,180,179,177,176,
  174,173,172,170,169,167,166,165,163,162,161,159,158,157,156,154,
  153,152,150,149,148,147,145,144,143,142,141,139,138,137,136,135,
  134,132,131,130,129,128,127,126,124,123,122,121,120,119,118,117,
  116,115,114,113,112,111,110,109,108,107,106,105,104,103,102,101,
  100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 88, 87, 86,
   85, 84, 83, 82, 81, 81, 80, 79, 78, 77, 76, 75, 75, 74, 73, 72,
   71, 70, 70, 69, 68, 67, 66, 66, 65, 64, 63, 63, 62, 61, 60, 59,
   59, 58, 57, 56, 56, 55, 54, 53, 53, 52, 51, 51, 50, 49, 48, 48,
   47, 46, 46, 45, 44, 44, 43, 42, 42, 41, 40, 40, 39, 38, 38, 37,
   36, 36, 35, 34, 34, 33, 32, 32, 31, 30, 30, 29, 29, 28, 27, 27,
   26, 26, 25, 24, 24, 23, 23, 22, 21, 21, 20, 20, 19, 18, 18, 17,
   17, 16, 16, 15, 15, 14, 13, 13, 12, 12, 11, 11, 10, 10,  9,  9,
    8,  7,  7,  6,  6,  5,  5,  4,  4,  3,  3,  2,  2,  1,  1,  0,
};

static const uint8_t armest_rsqrt_tab[384] = {
  255,253,251,249,247,245,243,242,240,238,236,234,233,231,229,228,
  226,224,223,221,219,218,216,215,213,212,210,209,207,206,204,203,
  201,200,198,197,196,194,193,192,190,189,188,186,185,184,183,181,
  180,179,178,176,175,174,173,172,170,169,168,167,166,165,164,163,
  162,160,159,158,157,156,155,154,153,152,151,150,149,148,147,146,
  145,144,143,142,141,140,140,139,138,137,136,135,134,133,132,131,
  131,130,129,128,127,126,126,125,124,123,122,121,121,120,119,118,
  118,117,116,115,114,114,113,112,111,111,110,109,109,108,107,106,
  105,105,104,104,103,103,101,101,100,100, 99, 99, 97, 97, 96, 96,
   95, 95, 93, 93, 92, 92, 91, 91, 90, 90, 88, 88, 87, 87, 86, 86,
   85, 85, 84, 84, 82, 82, 81, 81, 80, 80, 79, 79, 78, 78, 77, 77,
   76, 76, 75, 75, 74, 74, 72, 72, 71, 71, 70, 70, 69, 69, 68, 68,
   67, 67, 66, 66, 65, 65, 64, 64, 63, 63, 62, 62, 61, 61, 60, 60,
   60, 60, 59, 59, 58, 58, 57, 57, 56, 56, 55, 55, 54, 54, 53, 53,
   52, 52, 51, 51, 51, 51, 50, 50, 49, 49, 48, 48, 47, 47, 46, 46,
   46, 46, 45, 45, 44, 44, 43, 43, 42, 42, 42, 42, 41, 41, 40, 40,
   39, 39, 38, 38, 38, 38, 37, 37, 36, 36, 35, 35, 35, 35, 34, 34,
   33, 33, 33, 33, 32, 32, 31, 31, 30, 30, 30, 30, 29, 29, 28, 28,
   28, 28, 27, 27, 26, 26, 26, 26, 25, 25, 24, 24, 24, 24, 23, 23,
   22, 22, 22, 22, 21, 21, 20, 20, 20, 20, 19, 19, 19, 19, 18, 18,
   17, 17, 17, 17, 16, 16, 16, 16, 15, 15, 14, 14, 14, 14, 13, 13,
   13, 13, 12, 12, 11, 11, 11, 11, 10, 10, 10, 10,  9,  9,  9,  9,
    8,  8,  8,  8,  7,  7,  6,  6,  6,  6,  5,  5,  5,  5,  4,  4,
    4,  4,  3,  3,  3,  3,  2,  2,  2,  2,  1,  1,  1,  1,  0,  0,
};

static inline uint32_t arm_frecpe_f32(uint32_t x)
{
    uint32_t sign = x & 0x80000000u, ex = (x >> 23) & 0xffu, f = x & 0x7fffffu, rf;
    int e, re;
    if (ex == 0xffu) return f ? (x | 0x00400000u) : sign;   /* NaN: quiet; inf -> 0 */
    if (ex == 0) {
        if (f == 0) return sign | 0x7f800000u;               /* 0 -> inf (DZC) */
        if (f & 0x400000u) { e = 0; f = (f << 1) & 0x7fffffu; }
        else if (f & 0x200000u) { e = -1; f = (f << 2) & 0x7fffffu; }
        else return sign | 0x7f800000u;                      /* |x| < 2^-128: overflow, RNE -> inf */
    } else e = (int)ex;
    rf = (uint32_t)armest_recip_tab[f >> 15] << 15;
    re = 253 - e;
    if (re == 0) rf = 0x400000u | (rf >> 1);
    else if (re == -1) { rf = 0x200000u | (rf >> 2); re = 0; }
    return sign | ((uint32_t)re << 23) | rf;
}

static inline uint32_t arm_frsqrte_f32(uint32_t x)
{
    uint32_t ex = (x >> 23) & 0xffu, f = x & 0x7fffffu, scaled;
    int e;
    if (ex == 0xffu && f) return x | 0x00400000u;            /* NaN: quiet */
    if ((x & 0x7fffffffu) == 0) return x | 0x7f800000u;      /* +-0 -> +-inf */
    if (x & 0x80000000u) return 0x7fc00000u;                 /* negative -> default NaN */
    if (ex == 0xffu) return 0;                               /* +inf -> +0 */
    e = (int)ex;
    if (e == 0) {
        while (!(f & 0x400000u)) { f <<= 1; e--; }
        f = (f << 1) & 0x7fffffu;
    }
    scaled = ((unsigned)e & 1u) ? 128u + (f >> 16) : 256u + (f >> 15);
    return ((uint32_t)((380 - e) / 2) << 23) | ((uint32_t)armest_rsqrt_tab[scaled - 128] << 15);
}

/* ---- step instructions ---- */
static inline uint32_t armest_bits(float v) { uint32_t u; memcpy(&u, &v, 4); return u; }
static inline float armest_float(uint32_t u) { float v; memcpy(&v, &u, 4); return v; }

static inline int armest_clz64(uint64_t m)
{
    int n = 0;
    while (!(m & 0x8000000000000000ull)) { m <<= 1; n++; }
    return n;
}

/* Round sign * m * 2^e (m != 0) to binary32, round-to-nearest-even, no FTZ. */
static inline uint32_t armest_round(uint32_t sign, uint64_t m, int e)
{
    int lz = armest_clz64(m), bexp, sh;
    uint64_t kept, rem, half;
    m <<= lz; e -= lz;                    /* m in [2^63, 2^64) */
    bexp = e + 63 + 127;
    sh = 40;
    if (bexp < 1) { sh += 1 - bexp; bexp = 0; }
    if (sh > 64) return sign;             /* below half the smallest subnormal */
    if (sh == 64) { kept = 0; rem = m; half = 0x8000000000000000ull; }
    else { kept = m >> sh; rem = m & ((1ull << sh) - 1); half = 1ull << (sh - 1); }
    if (rem > half || (rem == half && (kept & 1))) kept++;
    if (bexp == 0) return sign | (uint32_t)kept;          /* subnormal (carry -> min normal) */
    if (bexp >= 255 || ((uint64_t)(bexp - 1) << 23) + kept >= 0x7f800000u)
        return sign | 0x7f800000u;                         /* overflow, RNE -> inf */
    return sign | (uint32_t)(((uint64_t)(bexp - 1) << 23) + kept);
}

/* C + na*b with single rounding, then optionally halved; na = -a already applied.
 * Operands finite, not NaN, not (inf,0). */
static inline uint32_t armest_fused(uint32_t na, uint32_t b, uint64_t C, int halve)
{
    uint32_t ea = (na >> 23) & 0xffu, eb = (b >> 23) & 0xffu, psign = (na ^ b) & 0x80000000u, rsign;
    uint64_t ma = na & 0x7fffffu, mb = b & 0x7fffffu, pm, cm = C, big, sm;
    int pe, ce = 0, be, d, s;
    if (ea) ma |= 0x800000u; else ea = 1;
    if (eb) mb |= 0x800000u; else eb = 1;
    pm = ma * mb;
    if (pm == 0) return armest_round(0, C, halve ? -1 : 0);
    pe = (int)ea + (int)eb - 300;
    s = armest_clz64(pm) - 2; pm <<= s; pe -= s;           /* top bit at 61 */
    s = armest_clz64(cm) - 2; cm <<= s; ce -= s;
    if (pe > ce) { big = pm; be = pe; sm = cm; d = pe - ce; rsign = psign; }
    else { big = cm; be = ce; sm = pm; d = ce - pe; rsign = 0; }
    if (d >= 63) sm = 1;
    else if (d) sm = (sm >> d) | ((sm & ((1ull << d) - 1)) != 0);
    if (!psign) big += sm;                                  /* product term positive */
    else if (big >= sm) big -= sm;
    else { big = sm - big; rsign = psign; }
    if (big == 0) return 0;                                 /* exact zero: +0 under RNE */
    return armest_round(rsign, big, be - (halve ? 1 : 0));
}

static inline int armest_step_special(uint32_t na, uint32_t b, uint32_t *r, uint32_t inf0)
{
    uint32_t aa = na & 0x7fffffffu, ab = b & 0x7fffffffu;
    if (aa > 0x7f800000u && !(na & 0x400000u)) { *r = na | 0x400000u; return 1; }
    if (ab > 0x7f800000u && !(b & 0x400000u)) { *r = b | 0x400000u; return 1; }
    if (aa > 0x7f800000u) { *r = na; return 1; }
    if (ab > 0x7f800000u) { *r = b; return 1; }
    if ((aa == 0x7f800000u && ab == 0) || (aa == 0 && ab == 0x7f800000u)) { *r = inf0; return 1; }
    if (aa == 0x7f800000u || ab == 0x7f800000u) { *r = ((na ^ b) & 0x80000000u) | 0x7f800000u; return 1; }
    return 0;
}

/* FRECPS: 2 - a*b fused. Note op1 is negated before NaN handling (AH=0), so a NaN in a comes back sign-flipped. */
static inline float arm_frecps_f32(float a, float b)
{
    uint32_t na = armest_bits(a) ^ 0x80000000u, bb = armest_bits(b), r;
    if (!armest_step_special(na, bb, &r, 0x40000000u)) r = armest_fused(na, bb, 2, 0);
    return armest_float(r);
}

/* FRSQRTS: (3 - a*b)/2 fused. */
static inline float arm_frsqrts_f32(float a, float b)
{
    uint32_t na = armest_bits(a) ^ 0x80000000u, bb = armest_bits(b), r;
    if (!armest_step_special(na, bb, &r, 0x3fc00000u)) r = armest_fused(na, bb, 3, 1);
    return armest_float(r);
}

#endif
