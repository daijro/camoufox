/*
 * sin, cos and tan as computed by the Windows Universal CRT (ucrtbase.dll
 * 10.0.22621.3593, x64) on its FMA3 code path, reproduced bit-exactly.
 *
 * Translated from the disassembly via a Python model that matched ucrtbase on
 * 80,002 random and 69,627 edge-case inputs per function, and real Windows
 * Firefox 152 on 3,997. Each fma() is one vfmadd/vfmsub/vfnmadd instruction;
 * every other operation is a single IEEE double op, so this must not be built
 * with FP contraction (pragma below, and -ffp-contract=off in moz.build).
 * Floating-point exception and errno side effects are not reproduced; NaN and
 * infinite arguments return NaN, which SpiderMonkey canonicalizes anyway.
 */
#include "builtin/UcrtMath.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

/* GCC ignores this pragma (and warns); -ffp-contract=off covers it there. */
#ifdef __clang__
#  pragma STDC FP_CONTRACT OFF
#endif

#if defined(__i386__) && !defined(__SSE2_MATH__)
#  error "ucrt_trig needs SSE2 double arithmetic (no x87 excess precision)"
#endif

#define SIGN 0x8000000000000000ULL
#define MANT 0x000fffffffffffffULL

static inline uint64_t bits(double x) {
  uint64_t b;
  memcpy(&b, &x, sizeof b);
  return b;
}

static inline double dbl(uint64_t b) {
  double x;
  memcpy(&x, &b, sizeof x);
  return x;
}

/* Bit patterns of the constants, by the ucrtbase address they were read from. */
#define K_ONE 0x3ff0000000000000ULL          /* 1800cca60, 1800d2bc0, 1800d2ee8 */
#define K_HALF 0x3fe0000000000000ULL         /* 1800ccaa8, 1800d2c18 */
#define K_PIBY4 0x3fe921fb54442d18ULL        /* 1800ccac8, 1800d2c38, 1800d2e60 */
#define K_TINY 0x3e40000000000000ULL         /* 1800ccab8, 1800d2c28, 1800d2eb0: 2^-27 */
#define K_SMALL 0x3f20000000000000ULL        /* 1800ccac0, 1800d2c30: 2^-13 */
#define K_LARGE 0x417312d000000000ULL        /* 1800ccad8, 1800d2c48, 1800d2f10: 2e7 */
#define K_INF 0x7ff0000000000000ULL          /* 1800ccae8, 1800d2c50, 1800d2ec0 */
#define K_SIXTH 0x3fc5555555555555ULL        /* 1800d2c20 */

/* reduce_medium */
#define K_TWOBYPI 0x3fe45f306dc9c883ULL      /* 1800d2b30 */
#define K_PIBY2_1 0x3ff921fb54442d18ULL      /* 1800d2b40 */
#define K_PIBY2_2 0x3c91a62633145c00ULL      /* 1800d2b50 */
#define K_PIBY2_3 0x397b839a252049c0ULL      /* 1800d2b60 */
#define K_SHIFT 0x4338000000000000ULL        /* 1800d2b70 */

/* reduce_large */
#define K_PIBY2 0x3ff921fb54442d18ULL        /* 1800d2a20 */
#define K_HI_MASK 0xfffffffff8000000ULL      /* 1800d2a30 */
#define K_PIBY2_H 0x3ff921fb50000000ULL      /* 1800d2a40 */
#define K_PIBY2_M 0x3e5110b460000000ULL      /* 1800d2a50 */
#define K_PIBY2_L 0x3c91a62633145c06ULL      /* 1800d2a60 */

/* tan */
#define K_PIBY4_LO 0x3c81a62633145c06ULL     /* 1800d2e70 */
#define K_POINT68 0x3fe5c28f5c28f5c3ULL      /* 1800d2ed0 */
#define K_NPOINT68 0xbfe5c28f5c28f5c3ULL     /* 1800d2ed8 */
#define K_MONE 0xbff0000000000000ULL         /* 1800d2ef0 */
#define K_TWO 0x4000000000000000ULL          /* 1800d2ef8 */
#define K_TAN_MASK 0xffffffff00000000ULL     /* 1800d2e50 */

static const uint64_t COS_C[6] = {
    0x3fa5555555555555ULL, 0xbf56c16c16c16967ULL, 0x3efa01a019f4ec91ULL,
    0xbe927e4fa17f667bULL, 0x3e21eeb690382eecULL, 0xbda907db47258aa7ULL,
};
static const uint64_t SIN_C[6] = {
    0xbfc5555555555555ULL, 0x3f81111111110bb3ULL, 0xbf2a01a019e83e5cULL,
    0x3ec71de3796cde01ULL, 0xbe5ae600b42fdfa7ULL, 0x3de5e0b2f9a43bb8ULL,
};
static const uint64_t TAN_P[3] = {
    0x3fd7d50f6638564aULL, 0xbf977c24c7569abbULL, 0x3f2d5daf289c385aULL,
};
static const uint64_t TAN_Q[4] = {
    0x3ff1dfcb8caa40b8ULL, 0xbfe08046499eb90fULL, 0x3f9ab0f4f80a0acfULL,
    0xbf2e7517ef6d98f8ULL,
};

/* Bits of 2/pi, byte-addressed (ucrtbase 1800cce40, first 0x100 bytes). */
static const uint8_t TWOBYPI[256] = {
    0xe0, 0xf1, 0x1b, 0xc1, 0x0c, 0x58, 0x21, 0x74, 0x35, 0x7e, 0xc4, 0x7e,
    0xed, 0xaf, 0xa9, 0x4b, 0x4a, 0x29, 0xde, 0xe7, 0x1c, 0xf4, 0xec, 0xc5,
    0x97, 0xaf, 0x1f, 0xeb, 0x9e, 0xd4, 0xb5, 0xa8, 0x7f, 0x79, 0x9a, 0xfd,
    0x18, 0x3d, 0xdd, 0x26, 0x2c, 0x9f, 0x3c, 0xfb, 0xd9, 0xb4, 0x7d, 0xb4,
    0x29, 0x68, 0x2d, 0x46, 0xbc, 0xbc, 0x3f, 0x60, 0x16, 0x78, 0xff, 0x5f,
    0xe2, 0x7f, 0xec, 0xa0, 0xe4, 0xf7, 0x2e, 0x7e, 0x11, 0x72, 0xd2, 0xe7,
    0x4c, 0x0d, 0xe6, 0x58, 0x47, 0xe6, 0x04, 0xf9, 0x7d, 0xd1, 0x9a, 0xc0,
    0x71, 0xa6, 0x13, 0x12, 0xed, 0xba, 0xd4, 0xd7, 0x08, 0xa2, 0xfb, 0x9c,
    0xa6, 0xc4, 0x72, 0xac, 0x77, 0xf8, 0x73, 0x48, 0x46, 0x27, 0xa8, 0xbb,
    0x24, 0x19, 0x80, 0x4b, 0x37, 0x09, 0xe9, 0xb8, 0x91, 0xdc, 0x86, 0x15,
    0xef, 0x7a, 0xaf, 0x8e, 0x45, 0xf9, 0x07, 0x41, 0x0e, 0xf1, 0x64, 0x56,
    0x8a, 0x6d, 0x03, 0x77, 0xd3, 0xd4, 0x47, 0x5f, 0x9d, 0xf0, 0xa7, 0x54,
    0x10, 0x39, 0xb9, 0x0d, 0xe6, 0x8b, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0xff,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0xf0, 0x7f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf8, 0xff, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
};

static inline uint64_t load64(int off) {
  uint64_t v = 0;
  for (int i = 7; i >= 0; i--) {
    v = (v << 8) | TWOBYPI[off + i];
  }
  return v;
}

/* bsr leaves the destination unchanged when the source is zero (AMD and Intel). */
static inline uint64_t bsr(uint64_t v, uint64_t dest) {
  return v ? (uint64_t)(63 - __builtin_clzll(v)) : dest;
}

/* 0x1800360c0: |x| < 2e7. */
static double reduce_medium(double x, double* rr, int* region) {
  double shift = dbl(K_SHIFT);
  double npi2 = fma(x, dbl(K_TWOBYPI), shift) - shift;
  *region = (int)npi2 & 3;
  double piby2_2 = dbl(K_PIBY2_2);
  double rhead = fma(-npi2, dbl(K_PIBY2_1), x);
  double rtail = npi2 * piby2_2;
  double err = fma(piby2_2, npi2, -rtail);
  double r5 = rhead - rtail;
  double t4 = (rhead - r5) - rtail;
  double rhead2 = fma(-npi2, piby2_2, rhead);
  r5 = ((r5 - rhead2) + t4) - err;
  *rr = fma(-npi2, dbl(K_PIBY2_3), r5);
  return rhead2;
}

/* 0x180035ed0: Payne-Hanek with 64x64->128 multiplies over the 2/pi table. */
static double reduce_large(double x, double* rr, int* region) {
  uint64_t xb = bits(x);
  uint64_t e = (xb >> 52) - 0x3FF;
  int off = 0x86 - (int)(e >> 3);
  uint64_t m = (xb & MANT) | (1ULL << 52);

  unsigned __int128 p0 = (unsigned __int128)load64(off) * m;
  uint64_t r8 = (uint64_t)p0, r10 = (uint64_t)(p0 >> 64);
  unsigned __int128 p1 = (unsigned __int128)load64(off + 8) * m;
  unsigned __int128 s = (unsigned __int128)(uint64_t)p1 + r10;
  uint64_t r9 = (uint64_t)s;
  r10 = (uint64_t)(p1 >> 64) + (uint64_t)(s >> 64);
  r10 += load64(off + 16) * m;

  uint64_t r11 = e & 7;
  unsigned cl = (unsigned)((0x36 - r11) & 63);
  uint64_t rax = r10 >> cl;
  uint64_t cf = cl ? (r10 >> (cl - 1)) & 1 : 0;
  uint64_t rdx = 0;
  if (cf) {
    r10 = ~r10;
    r9 = ~r9;
    r8 = ~r8;
    rdx = SIGN;
  }
  *region = (int)((rax + cf) & 3);

  cl = (unsigned)((r11 + 10) & 63);
  r10 = (r10 << cl) >> cl;
  uint64_t rcx = bsr(r10, r11 + 10);
  r11 = r11 + 10 - 0x40;
  if (r10 == 0) {
    r10 = r9;
    r9 = r8;
    r8 = 0;
    rcx = bsr(r10, rcx);
    r11 -= 0x40;
  }
  r11 += rcx;
  rcx -= 0x34;
  if ((int64_t)rcx > 0) {
    unsigned c = (unsigned)(rcx & 63);
    uint64_t top = r10;
    r10 >>= c;
    r9 >>= c;
    r9 |= top << ((0x40 - rcx) & 63);
  } else if ((int64_t)rcx < 0) {
    uint64_t n = -rcx;
    unsigned c = (unsigned)(n & 63);
    unsigned c2 = (unsigned)((0x40 - n) & 63);
    uint64_t low = r9;
    r10 <<= c;
    r9 <<= c;
    r10 |= low >> c2;
    r8 >>= c2;
    r9 |= r8;
  }
  r11 += 0x3FF;
  r10 &= ~(1ULL << 52);
  r10 |= rdx;
  rcx = r11 << 52;
  r10 |= rcx;
  double hi = dbl(r10);

  rcx = bsr(r9, rcx);
  rcx = 0x40 - rcx;
  r9 = (r9 << (rcx & 63)) >> 12;
  rcx += 0x34;
  r11 -= rcx;
  r9 |= rdx | (r11 << 52);
  double lo = dbl(r9);

  double piby2 = dbl(K_PIBY2), p1h = dbl(K_PIBY2_H), p2 = dbl(K_PIBY2_M);
  double hi_top = dbl(bits(hi) & K_HI_MASK);
  double hi_bot = hi - hi_top;
  double r5 = hi * piby2;
  double t = hi_top * p1h - r5;
  t = fma(hi_bot, p1h, t);
  t = fma(hi_top, p2, t);
  t = fma(hi_bot, p2, t);
  double u = fma(hi, dbl(K_PIBY2_L), lo * piby2);
  t = t + u;
  double r = r5 + t;
  *rr = (r5 - r) + t;
  return r;
}

static double reduce(double ax, double* rr, int* region) {
  if (bits(ax) >= K_LARGE) {
    return reduce_large(ax, rr, region);
  }
  return reduce_medium(ax, rr, region);
}

static double cos_kernel(double r, double rr, double x2) {
  double one = dbl(K_ONE);
  double h = x2 * dbl(K_HALF);
  double t = one - h;
  double tail = fma(-r, rr, (one - t) - h);
  double p = fma(x2, dbl(COS_C[5]), dbl(COS_C[4]));
  for (int k = 3; k >= 0; k--) {
    p = fma(p, x2, dbl(COS_C[k]));
  }
  return fma(p, x2 * x2, tail) + t;
}

static double sin_kernel(double r, double rr, double x2) {
  double p = fma(x2, dbl(SIN_C[5]), dbl(SIN_C[4]));
  for (int k = 3; k >= 1; k--) {
    p = fma(p, x2, dbl(SIN_C[k]));
  }
  double x3 = r * x2;
  double t = (rr * dbl(K_HALF)) - x3 * p;
  t = x2 * t - rr;
  t = fma(-x3, dbl(SIN_C[0]), t);
  return r - t;
}

double ucrt_sin(double x) {
  uint64_t xb = bits(x);
  uint64_t a = xb & ~SIGN;
  if (a >= K_PIBY4) {
    if (a >= K_INF) {
      return NAN;
    }
    double rr;
    int region;
    double r = reduce(dbl(a), &rr, &region);
    double x2 = r * r;
    double res = (region & 1) ? cos_kernel(r, rr, x2) : sin_kernel(r, rr, x2);
    uint64_t flip = ((region & 2) ? SIGN : 0) ^ (xb & SIGN);
    return dbl(bits(res) ^ flip);
  }
  if (a >= K_SMALL) {
    double x2 = x * x;
    double p = fma(x2, dbl(SIN_C[5]), dbl(SIN_C[4]));
    for (int k = 3; k >= 0; k--) {
      p = fma(p, x2, dbl(SIN_C[k]));
    }
    return fma(x * x2, p, x);
  }
  if (a >= K_TINY) {
    return fma(-((x * x) * x), dbl(K_SIXTH), x);
  }
  return x;
}

double ucrt_cos(double x) {
  uint64_t xb = bits(x);
  uint64_t a = xb & ~SIGN;
  double one = dbl(K_ONE);
  if (a > K_PIBY4) {
    if ((xb & K_INF) == K_INF) {
      return NAN;
    }
    double rr;
    int region;
    double r = reduce(dbl(a), &rr, &region);
    double x2 = r * r;
    double res = (region & 1) ? sin_kernel(r, rr, x2) : cos_kernel(r, rr, x2);
    uint64_t flip = ((region + 1) & 2) ? SIGN : 0;
    return dbl(bits(res) ^ flip);
  }
  if (a >= K_SMALL) {
    double x2 = x * x;
    double p = fma(dbl(COS_C[5]), x2, dbl(COS_C[4]));
    for (int k = 3; k >= 0; k--) {
      p = fma(p, x2, dbl(COS_C[k]));
    }
    p = fma(x2, p, -dbl(K_HALF));
    return fma(x2, p, one);
  }
  if (a >= K_TINY) {
    return fma(-(x * dbl(K_HALF)), x, one);
  }
  return one;
}

static double tan_poly(double x2, double* q_out) {
  double q = fma(dbl(TAN_Q[3]), x2, dbl(TAN_Q[2]));
  double p = fma(dbl(TAN_P[2]), x2, dbl(TAN_P[1]));
  q = fma(q, x2, dbl(TAN_Q[1]));
  p = fma(p, x2, dbl(TAN_P[0]));
  q = fma(q, x2, dbl(TAN_Q[0]));
  *q_out = q;
  return p;
}

double ucrt_tan(double x) {
  uint64_t xb = bits(x);
  uint64_t a = xb & ~SIGN;
  double piby4 = dbl(K_PIBY4), piby4_lo = dbl(K_PIBY4_LO);
  double one = dbl(K_ONE), two = dbl(K_TWO);

  if (a < K_PIBY4) {
    double w = 0.0;
    if (a > K_POINT68) {
      if (x < 0.0) {
        w = dbl(K_MONE);
        x = (piby4 + x) + piby4_lo;
      } else {
        w = one;
        x = (piby4 - x) + piby4_lo;
      }
    } else if (a < K_TINY) {
      return x;
    }
    double x2 = x * x;
    double q;
    double p = tan_poly(x2, &q);
    x = fma(x, (p / q) * x2, x);
    if (w == 0.0) {
      return x;
    }
    return fma(-(x / (x + one)), two, one) * w;
  }

  if (a >= K_INF) {
    return NAN;
  }
  double rr;
  int region;
  double r = reduce(dbl(a), &rr, &region);
  double w = 0.0;
  if (r > dbl(K_POINT68)) {
    w = one;
    r = (piby4 - r) + (piby4_lo - rr);
    rr = 0.0;
  } else if (!(r >= dbl(K_NPOINT68))) {
    w = dbl(K_MONE);
    r = (piby4 + r) + (piby4_lo + rr);
    rr = 0.0;
  }
  double r2 = fma(rr * r, two, r * r);
  double p = fma(dbl(TAN_P[2]), r2, dbl(TAN_P[1]));
  p = fma(p, r2, dbl(TAN_P[0]));
  double q = fma(dbl(TAN_Q[3]), r2, dbl(TAN_Q[2]));
  q = fma(q, r2, dbl(TAN_Q[1]));
  q = fma(q, r2, dbl(TAN_Q[0]));
  double tail = fma(r, (p / q) * r2, rr);
  double t = r + tail;
  double res;
  if (w != 0.0) {
    if (region & 1) {
      res = fma(t / (t - one), two, -one) * w;
    } else {
      res = fma(-(t / (t + one)), two, one) * w;
    }
  } else if (region & 1) {
    double t_hi = dbl(bits(t) & K_TAN_MASK);
    double tail2 = tail - (t_hi - r);
    double z = dbl(K_MONE) / t;
    double z_hi = dbl(bits(z) & K_TAN_MASK);
    double u = fma(z_hi, t_hi, one);
    u = fma(tail2, z_hi, u);
    res = fma(z, u, z_hi);
  } else {
    res = t;
  }
  return dbl(bits(res) ^ (xb & SIGN));
}
