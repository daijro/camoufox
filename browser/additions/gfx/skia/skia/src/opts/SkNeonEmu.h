/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The AArch64 NEON intrinsics Skia's ARM code paths use, implemented on
// x86-64 with the result an Apple M or Cortex-A core gives, bit for bit
// (FPCR at the Linux/macOS default: no flush-to-zero, no default-NaN mode,
// round to nearest even). Code written for <arm_neon.h> compiles against
// this header instead, so an x86-64 build can draw and mix audio as an
// ARM64 machine does when general.cpu_identity names ARM64.
//
// The vector types are clang/GCC vectors of the same lane type and count as
// NEON's, so they also accept the generic vector operators NEON code uses.
// Lane-wise integer operations are the same everywhere; the floating-point
// ones follow the Arm ARM pseudocode, including the estimate instructions
// (FRECPE/FRSQRTE and their Newton steps, ArmEstimates.h), fused
// multiply-add, FMIN/FMAX, the float-to-integer conversions (saturating,
// NaN to 0) and NaN propagation in each.

#ifndef SkNeonEmu_DEFINED
#define SkNeonEmu_DEFINED

#include <math.h>
#include <stdint.h>
#include <string.h>

#include "src/opts/SkArmEstimates.h"

#if defined(__clang__)
#  define NEON_EMU_VEC(T, N) T __attribute__((ext_vector_type(N)))
#else
#  define NEON_EMU_VEC(T, N) T __attribute__((vector_size(N * sizeof(T))))
#endif
#define NEON_EMU_SI static inline __attribute__((always_inline))

typedef NEON_EMU_VEC(int8_t, 8) int8x8_t;
typedef NEON_EMU_VEC(int8_t, 16) int8x16_t;
typedef NEON_EMU_VEC(uint8_t, 8) uint8x8_t;
typedef NEON_EMU_VEC(uint8_t, 16) uint8x16_t;
typedef NEON_EMU_VEC(int16_t, 4) int16x4_t;
typedef NEON_EMU_VEC(int16_t, 8) int16x8_t;
typedef NEON_EMU_VEC(uint16_t, 4) uint16x4_t;
typedef NEON_EMU_VEC(uint16_t, 8) uint16x8_t;
typedef NEON_EMU_VEC(int32_t, 2) int32x2_t;
typedef NEON_EMU_VEC(int32_t, 4) int32x4_t;
typedef NEON_EMU_VEC(uint32_t, 2) uint32x2_t;
typedef NEON_EMU_VEC(uint32_t, 4) uint32x4_t;
typedef NEON_EMU_VEC(int64_t, 1) int64x1_t;
typedef NEON_EMU_VEC(int64_t, 2) int64x2_t;
typedef NEON_EMU_VEC(uint64_t, 1) uint64x1_t;
typedef NEON_EMU_VEC(uint64_t, 2) uint64x2_t;
typedef NEON_EMU_VEC(float, 2) float32x2_t;
typedef NEON_EMU_VEC(float, 4) float32x4_t;
// Half floats travel as their bits.
typedef NEON_EMU_VEC(uint16_t, 4) float16x4_t;
typedef float float32_t;

#define NEON_EMU_STRUCTS(T)    \
  typedef struct {             \
    T##_t val[2];              \
  } T##x2_t;                   \
  typedef struct {             \
    T##_t val[3];              \
  } T##x3_t;                   \
  typedef struct {             \
    T##_t val[4];              \
  } T##x4_t;
NEON_EMU_STRUCTS(int8x8)
NEON_EMU_STRUCTS(int8x16)
NEON_EMU_STRUCTS(uint8x8)
NEON_EMU_STRUCTS(uint8x16)
NEON_EMU_STRUCTS(int16x4)
NEON_EMU_STRUCTS(int16x8)
NEON_EMU_STRUCTS(uint16x4)
NEON_EMU_STRUCTS(uint16x8)
NEON_EMU_STRUCTS(int32x2)
NEON_EMU_STRUCTS(int32x4)
NEON_EMU_STRUCTS(uint32x2)
NEON_EMU_STRUCTS(uint32x4)
NEON_EMU_STRUCTS(float32x2)
NEON_EMU_STRUCTS(float32x4)
#undef NEON_EMU_STRUCTS

#define NEON_EMU_LANES(V) ((int)(sizeof(V) / sizeof((V)[0])))

// ---- floating point: the Arm ARM's NaN and rounding rules ----------------

NEON_EMU_SI uint32_t neon_emu_bits(float f) {
  uint32_t u;
  memcpy(&u, &f, 4);
  return u;
}
NEON_EMU_SI float neon_emu_float(uint32_t u) {
  float f;
  memcpy(&f, &u, 4);
  return f;
}
NEON_EMU_SI int neon_emu_isnan(uint32_t u) {
  return (u & 0x7fffffffu) > 0x7f800000u;
}
NEON_EMU_SI int neon_emu_issnan(uint32_t u) {
  return neon_emu_isnan(u) && !(u & 0x400000u);
}
static const uint32_t kNeonEmuDefaultNaN = 0x7fc00000u;

// FPProcessNaNs: a signalling NaN first (quieted), then a quiet one; op1
// before op2. Returns 1 and sets *r when either is a NaN.
NEON_EMU_SI int neon_emu_nans2(uint32_t a, uint32_t b, uint32_t* r) {
  if (neon_emu_issnan(a)) return *r = a | 0x400000u, 1;
  if (neon_emu_issnan(b)) return *r = b | 0x400000u, 1;
  if (neon_emu_isnan(a)) return *r = a, 1;
  if (neon_emu_isnan(b)) return *r = b, 1;
  return 0;
}

NEON_EMU_SI float neon_emu_fmin(float a, float b) {
  uint32_t ua = neon_emu_bits(a), ub = neon_emu_bits(b), r;
  if (neon_emu_nans2(ua, ub, &r)) return neon_emu_float(r);
  if (a == b) return neon_emu_float(ua | ub);  // -0 below +0
  return a < b ? a : b;
}
NEON_EMU_SI float neon_emu_fmax(float a, float b) {
  uint32_t ua = neon_emu_bits(a), ub = neon_emu_bits(b), r;
  if (neon_emu_nans2(ua, ub, &r)) return neon_emu_float(r);
  if (a == b) return neon_emu_float(ua & ub);
  return a > b ? a : b;
}

// FPMulAdd(addend, op1, op2): addend + op1*op2, one rounding.
NEON_EMU_SI float neon_emu_fmla(float addend, float op1, float op2) {
  uint32_t ua = neon_emu_bits(addend), u1 = neon_emu_bits(op1),
           u2 = neon_emu_bits(op2);
  int inf1 = (u1 & 0x7fffffffu) == 0x7f800000u,
      inf2 = (u2 & 0x7fffffffu) == 0x7f800000u;
  int zero1 = !(u1 & 0x7fffffffu), zero2 = !(u2 & 0x7fffffffu);
  int infzero = (inf1 && zero2) || (zero1 && inf2);
  if (neon_emu_isnan(ua) && !neon_emu_issnan(ua) && infzero) {
    return neon_emu_float(kNeonEmuDefaultNaN);
  }
  if (neon_emu_issnan(ua)) return neon_emu_float(ua | 0x400000u);
  if (neon_emu_issnan(u1)) return neon_emu_float(u1 | 0x400000u);
  if (neon_emu_issnan(u2)) return neon_emu_float(u2 | 0x400000u);
  if (neon_emu_isnan(ua)) return addend;
  if (neon_emu_isnan(u1)) return op1;
  if (neon_emu_isnan(u2)) return op2;
  float r = __builtin_fmaf(op1, op2, addend);
  if (neon_emu_isnan(neon_emu_bits(r))) {
    return neon_emu_float(kNeonEmuDefaultNaN);  // inf*0 or inf-inf
  }
  return r;
}

// One of FADD/FSUB/FMUL/FDIV's NaN results; otherwise the x86 result (the
// value is the same IEEE operation).
NEON_EMU_SI float neon_emu_arith_nan(float a, float b, float x86) {
  uint32_t r;
  if (neon_emu_nans2(neon_emu_bits(a), neon_emu_bits(b), &r)) {
    return neon_emu_float(r);
  }
  if (neon_emu_isnan(neon_emu_bits(x86))) {
    return neon_emu_float(kNeonEmuDefaultNaN);
  }
  return x86;
}

NEON_EMU_SI float neon_emu_quiet(float a) {
  uint32_t u = neon_emu_bits(a);
  return neon_emu_isnan(u) ? neon_emu_float(u | 0x400000u) : a;
}

NEON_EMU_SI float neon_emu_fsqrt(float a) {
  uint32_t u = neon_emu_bits(a);
  if (neon_emu_isnan(u)) return neon_emu_float(u | 0x400000u);
  if ((u & 0x80000000u) && (u & 0x7fffffffu)) {
    return neon_emu_float(kNeonEmuDefaultNaN);
  }
  return __builtin_sqrtf(a);
}

// FCVTZS/FCVTZU/FCVTNS/FCVTNU: saturate, NaN to 0.
NEON_EMU_SI int32_t neon_emu_f2s(float f) {
  if (f != f) return 0;
  if (f >= 2147483648.0f) return INT32_MAX;
  if (f < -2147483648.0f) return INT32_MIN;
  return (int32_t)f;
}
NEON_EMU_SI uint32_t neon_emu_f2u(float f) {
  if (f != f || f <= -1.0f) return 0;
  if (f >= 4294967296.0f) return UINT32_MAX;
  return f < 0 ? 0 : (uint32_t)f;
}
NEON_EMU_SI float neon_emu_rne(float f) {
  // Round to nearest, ties to even; NaN quieted.
  if (f != f) return neon_emu_quiet(f);
  return __builtin_roundevenf(f);
}

// Single to half and back (FCVT, FPCR.AHP 0, DN 0, round to nearest even).
NEON_EMU_SI uint16_t neon_emu_f32_to_f16(float f) {
  uint32_t u = neon_emu_bits(f), sign = (u >> 16) & 0x8000u;
  uint32_t e = (u >> 23) & 0xffu, m = u & 0x7fffffu;
  if (e == 0xff) {
    if (m) return (uint16_t)(sign | 0x7e00u | ((m >> 13) & 0x1ffu));
    return (uint16_t)(sign | 0x7c00u);
  }
  if (e == 0) return (uint16_t)sign;  // single subnormals round to 0
  int32_t he = (int32_t)e - 112;       // the half's biased exponent
  uint32_t full = m | 0x800000u;       // value = full * 2^(e - 150)
  int32_t shift = he >= 1 ? 13 : 13 + (1 - he);
  if (he < 1) he = 0;
  if (shift > 25) return (uint16_t)sign;
  uint32_t kept = full >> shift, rem = full & ((1u << shift) - 1),
           half = 1u << (shift - 1);
  if (rem > half || (rem == half && (kept & 1))) kept++;
  uint32_t out;
  if (he == 0) {
    out = kept;  // may carry into the smallest normal, which is correct
  } else {
    out = ((uint32_t)(he - 1) << 10) + kept;  // kept includes the implicit 1
  }
  if (out >= 0x7c00u) return (uint16_t)(sign | 0x7c00u);
  return (uint16_t)(sign | out);
}
NEON_EMU_SI float neon_emu_f16_to_f32(uint16_t h) {
  uint32_t sign = (uint32_t)(h & 0x8000u) << 16, e = (h >> 10) & 0x1fu,
           m = h & 0x3ffu;
  if (e == 0x1f) {
    if (m) return neon_emu_float(sign | 0x7fc00000u | ((m & 0x1ffu) << 13));
    return neon_emu_float(sign | 0x7f800000u);
  }
  if (e == 0) {
    if (!m) return neon_emu_float(sign);
    int s = 0;
    while (!(m & 0x400u)) {
      m <<= 1;
      s++;
    }
    return neon_emu_float(sign | ((uint32_t)(113 - s) << 23) |
                          ((m & 0x3ffu) << 13));
  }
  return neon_emu_float(sign | ((e + 112) << 23) | (m << 13));
}

#define NEON_EMU_MAP1(R, A, expr)                         \
  ({                                                      \
    R r_;                                                 \
    for (int i = 0; i < NEON_EMU_LANES(r_); i++) {        \
      r_[i] = (expr);                                     \
    }                                                     \
    r_;                                                   \
  })

NEON_EMU_SI float32x4_t vrecpeq_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       neon_emu_float(arm_frecpe_f32(neon_emu_bits(a[i]))));
}
NEON_EMU_SI float32x4_t vrsqrteq_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       neon_emu_float(arm_frsqrte_f32(neon_emu_bits(a[i]))));
}
NEON_EMU_SI float32x4_t vrecpsq_f32(float32x4_t a, float32x4_t b) {
  return NEON_EMU_MAP1(float32x4_t, a, arm_frecps_f32(a[i], b[i]));
}
NEON_EMU_SI float32x4_t vrsqrtsq_f32(float32x4_t a, float32x4_t b) {
  return NEON_EMU_MAP1(float32x4_t, a, arm_frsqrts_f32(a[i], b[i]));
}
NEON_EMU_SI float32x4_t vfmaq_f32(float32x4_t a, float32x4_t b,
                                  float32x4_t c) {
  return NEON_EMU_MAP1(float32x4_t, a, neon_emu_fmla(a[i], b[i], c[i]));
}
NEON_EMU_SI float32x4_t vfmsq_f32(float32x4_t a, float32x4_t b,
                                  float32x4_t c) {
  // FMLS negates op1 (b) first, a NaN's sign included.
  return NEON_EMU_MAP1(
      float32x4_t, a,
      neon_emu_fmla(a[i], neon_emu_float(neon_emu_bits(b[i]) ^ 0x80000000u),
                    c[i]));
}
NEON_EMU_SI float32x4_t vmulq_f32(float32x4_t a, float32x4_t b) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       neon_emu_arith_nan(a[i], b[i], a[i] * b[i]));
}
NEON_EMU_SI float32x4_t vaddq_f32(float32x4_t a, float32x4_t b) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       neon_emu_arith_nan(a[i], b[i], a[i] + b[i]));
}
NEON_EMU_SI float32x4_t vsubq_f32(float32x4_t a, float32x4_t b) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       neon_emu_arith_nan(a[i], b[i], a[i] - b[i]));
}
// FMUL then FADD/FSUB, two roundings.
NEON_EMU_SI float32x4_t vmlaq_f32(float32x4_t a, float32x4_t b,
                                  float32x4_t c) {
  return vaddq_f32(a, vmulq_f32(b, c));
}
NEON_EMU_SI float32x4_t vmlsq_f32(float32x4_t a, float32x4_t b,
                                  float32x4_t c) {
  return vsubq_f32(a, vmulq_f32(b, c));
}
NEON_EMU_SI float32x4_t vminq_f32(float32x4_t a, float32x4_t b) {
  return NEON_EMU_MAP1(float32x4_t, a, neon_emu_fmin(a[i], b[i]));
}
NEON_EMU_SI float32x4_t vmaxq_f32(float32x4_t a, float32x4_t b) {
  return NEON_EMU_MAP1(float32x4_t, a, neon_emu_fmax(a[i], b[i]));
}
NEON_EMU_SI float32x4_t vabsq_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       neon_emu_float(neon_emu_bits(a[i]) & 0x7fffffffu));
}
NEON_EMU_SI float32x4_t vsqrtq_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a, neon_emu_fsqrt(a[i]));
}
NEON_EMU_SI float32x4_t vrndmq_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       a[i] != a[i] ? neon_emu_quiet(a[i]) : __builtin_floorf(a[i]));
}
NEON_EMU_SI float32x4_t vrndpq_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a,
                       a[i] != a[i] ? neon_emu_quiet(a[i]) : __builtin_ceilf(a[i]));
}
NEON_EMU_SI float32x4_t vrndnq_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a, neon_emu_rne(a[i]));
}
NEON_EMU_SI float32_t vrndns_f32(float32_t a) { return neon_emu_rne(a); }
NEON_EMU_SI int32x4_t vcvtq_s32_f32(float32x4_t a) {
  return NEON_EMU_MAP1(int32x4_t, a, neon_emu_f2s(a[i]));
}
NEON_EMU_SI uint32x4_t vcvtq_u32_f32(float32x4_t a) {
  return NEON_EMU_MAP1(uint32x4_t, a, neon_emu_f2u(a[i]));
}
NEON_EMU_SI int32x4_t vcvtnq_s32_f32(float32x4_t a) {
  return NEON_EMU_MAP1(int32x4_t, a, neon_emu_f2s(neon_emu_rne(a[i])));
}
NEON_EMU_SI uint32x4_t vcvtnq_u32_f32(float32x4_t a) {
  return NEON_EMU_MAP1(uint32x4_t, a, neon_emu_f2u(neon_emu_rne(a[i])));
}
NEON_EMU_SI float32x4_t vcvtq_f32_s32(int32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a, (float)a[i]);
}
NEON_EMU_SI float32x4_t vcvtq_f32_u32(uint32x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a, (float)a[i]);
}
NEON_EMU_SI float16x4_t vcvt_f16_f32(float32x4_t a) {
  return NEON_EMU_MAP1(float16x4_t, a, neon_emu_f32_to_f16(a[i]));
}
NEON_EMU_SI float32x4_t vcvt_f32_f16(float16x4_t a) {
  return NEON_EMU_MAP1(float32x4_t, a, neon_emu_f16_to_f32(a[i]));
}
NEON_EMU_SI float32x4_t vbslq_f32(uint32x4_t m, float32x4_t a,
                                  float32x4_t b) {
  uint32x4_t ua, ub;
  memcpy(&ua, &a, 16);
  memcpy(&ub, &b, 16);
  uint32x4_t r = (m & ua) | (~m & ub);
  float32x4_t f;
  memcpy(&f, &r, 16);
  return f;
}
NEON_EMU_SI float32x4_t vdupq_n_f32(float v) { return (float32x4_t)v; }
NEON_EMU_SI float32x4_t vmulq_n_f32(float32x4_t a, float b) {
  return vmulq_f32(a, vdupq_n_f32(b));
}

// ---- integers -------------------------------------------------------------

#define NEON_EMU_BITCAST(R, x)                     \
  ({                                               \
    R r_;                                          \
    static_assert(sizeof(r_) == sizeof(x), "size"); \
    memcpy(&r_, &(x), sizeof(r_));                 \
    r_;                                            \
  })

// vreinterpret(q)_<to>_<from>
#define NEON_EMU_REINTERPRET(Q, TO, FROM, TOT, FROMT)            \
  NEON_EMU_SI TOT vreinterpret##Q##_##TO##_##FROM(FROMT a) {     \
    return NEON_EMU_BITCAST(TOT, a);                             \
  }
NEON_EMU_REINTERPRET(q, s16, u16, int16x8_t, uint16x8_t)
NEON_EMU_REINTERPRET(q, u16, s16, uint16x8_t, int16x8_t)
NEON_EMU_REINTERPRET(q, u8, u16, uint8x16_t, uint16x8_t)
NEON_EMU_REINTERPRET(q, u16, u8, uint16x8_t, uint8x16_t)
NEON_EMU_REINTERPRET(q, u8, u32, uint8x16_t, uint32x4_t)
NEON_EMU_REINTERPRET(q, u32, u8, uint32x4_t, uint8x16_t)
NEON_EMU_REINTERPRET(q, u16, u32, uint16x8_t, uint32x4_t)
NEON_EMU_REINTERPRET(q, u32, u16, uint32x4_t, uint16x8_t)
NEON_EMU_REINTERPRET(q, s32, u32, int32x4_t, uint32x4_t)
NEON_EMU_REINTERPRET(q, u32, s32, uint32x4_t, int32x4_t)
NEON_EMU_REINTERPRET(q, s16, u8, int16x8_t, uint8x16_t)
NEON_EMU_REINTERPRET(q, u8, s16, uint8x16_t, int16x8_t)
NEON_EMU_REINTERPRET(q, s8, u8, int8x16_t, uint8x16_t)
NEON_EMU_REINTERPRET(q, u8, s8, uint8x16_t, int8x16_t)
NEON_EMU_REINTERPRET(q, f32, u32, float32x4_t, uint32x4_t)
NEON_EMU_REINTERPRET(q, u32, f32, uint32x4_t, float32x4_t)
NEON_EMU_REINTERPRET(q, f32, s32, float32x4_t, int32x4_t)
NEON_EMU_REINTERPRET(q, s32, f32, int32x4_t, float32x4_t)
NEON_EMU_REINTERPRET(q, u64, u8, uint64x2_t, uint8x16_t)
NEON_EMU_REINTERPRET(q, u8, u64, uint8x16_t, uint64x2_t)
NEON_EMU_REINTERPRET(, u32, u8, uint32x2_t, uint8x8_t)
NEON_EMU_REINTERPRET(, u8, u32, uint8x8_t, uint32x2_t)
NEON_EMU_REINTERPRET(, u16, u8, uint16x4_t, uint8x8_t)
NEON_EMU_REINTERPRET(, u8, u16, uint8x8_t, uint16x4_t)
NEON_EMU_REINTERPRET(, s16, u16, int16x4_t, uint16x4_t)
NEON_EMU_REINTERPRET(, u16, s16, uint16x4_t, int16x4_t)
NEON_EMU_REINTERPRET(, u64, u8, uint64x1_t, uint8x8_t)
NEON_EMU_REINTERPRET(, u8, u64, uint8x8_t, uint64x1_t)
#undef NEON_EMU_REINTERPRET

// dup / mov / create
#define NEON_EMU_DUP(SUF, V, T)                               \
  NEON_EMU_SI V vdup_n_##SUF(T x) { return (V)x; }
#define NEON_EMU_DUPQ(SUF, V, T)                              \
  NEON_EMU_SI V vdupq_n_##SUF(T x) { return (V)x; }
NEON_EMU_DUP(u8, uint8x8_t, uint8_t)
NEON_EMU_DUP(u16, uint16x4_t, uint16_t)
NEON_EMU_DUP(u32, uint32x2_t, uint32_t)
NEON_EMU_DUP(s16, int16x4_t, int16_t)
NEON_EMU_DUPQ(u8, uint8x16_t, uint8_t)
NEON_EMU_DUPQ(u16, uint16x8_t, uint16_t)
NEON_EMU_DUPQ(u32, uint32x4_t, uint32_t)
NEON_EMU_DUPQ(s16, int16x8_t, int16_t)
NEON_EMU_DUPQ(s32, int32x4_t, int32_t)
#undef NEON_EMU_DUP
#undef NEON_EMU_DUPQ
NEON_EMU_SI uint8x8_t vmov_n_u8(uint8_t x) { return (uint8x8_t)x; }
NEON_EMU_SI uint16x4_t vmov_n_u16(uint16_t x) { return (uint16x4_t)x; }
NEON_EMU_SI uint8x16_t vmovq_n_u8(uint8_t x) { return (uint8x16_t)x; }
NEON_EMU_SI uint16x8_t vmovq_n_u16(uint16_t x) { return (uint16x8_t)x; }
NEON_EMU_SI uint8x8_t vcreate_u8(uint64_t x) { return NEON_EMU_BITCAST(uint8x8_t, x); }
NEON_EMU_SI uint16x4_t vcreate_u16(uint64_t x) { return NEON_EMU_BITCAST(uint16x4_t, x); }
NEON_EMU_SI uint32x2_t vcreate_u32(uint64_t x) { return NEON_EMU_BITCAST(uint32x2_t, x); }

// combine / get_high / get_low
#define NEON_EMU_HALVES(SUF, D, Q, T, N)                               \
  NEON_EMU_SI Q vcombine_##SUF(D lo, D hi) {                           \
    Q r;                                                               \
    memcpy(&r, &lo, sizeof(D));                                        \
    memcpy((char*)&r + sizeof(D), &hi, sizeof(D));                     \
    return r;                                                          \
  }                                                                    \
  NEON_EMU_SI D vget_low_##SUF(Q a) {                                  \
    D r;                                                               \
    memcpy(&r, &a, sizeof(D));                                         \
    return r;                                                          \
  }                                                                    \
  NEON_EMU_SI D vget_high_##SUF(Q a) {                                 \
    D r;                                                               \
    memcpy(&r, (const char*)&a + sizeof(D), sizeof(D));                \
    return r;                                                          \
  }
NEON_EMU_HALVES(u8, uint8x8_t, uint8x16_t, uint8_t, 8)
NEON_EMU_HALVES(s8, int8x8_t, int8x16_t, int8_t, 8)
NEON_EMU_HALVES(u16, uint16x4_t, uint16x8_t, uint16_t, 4)
NEON_EMU_HALVES(s16, int16x4_t, int16x8_t, int16_t, 4)
NEON_EMU_HALVES(u32, uint32x2_t, uint32x4_t, uint32_t, 2)
NEON_EMU_HALVES(s32, int32x2_t, int32x4_t, int32_t, 2)
NEON_EMU_HALVES(f32, float32x2_t, float32x4_t, float, 2)
#undef NEON_EMU_HALVES

// lanes
#define vget_lane_u8(v, l) ((uint8_t)(v)[(l)])
#define vget_lane_u16(v, l) ((uint16_t)(v)[(l)])
#define vget_lane_u32(v, l) ((uint32_t)(v)[(l)])
#define vgetq_lane_u8(v, l) ((uint8_t)(v)[(l)])
#define vgetq_lane_u16(v, l) ((uint16_t)(v)[(l)])
#define vgetq_lane_u32(v, l) ((uint32_t)(v)[(l)])
#define vgetq_lane_s32(v, l) ((int32_t)(v)[(l)])
#define vgetq_lane_f32(v, l) ((float)(v)[(l)])
NEON_EMU_SI uint32x2_t neon_emu_set_lane_u32(uint32_t x, uint32x2_t v, int l) {
  v[l] = x;
  return v;
}
#define vset_lane_u32(x, v, l) neon_emu_set_lane_u32((x), (v), (l))
NEON_EMU_SI uint32x4_t neon_emu_setq_lane_u32(uint32_t x, uint32x4_t v, int l) {
  v[l] = x;
  return v;
}
#define vsetq_lane_u32(x, v, l) neon_emu_setq_lane_u32((x), (v), (l))

// loads / stores
#define NEON_EMU_LD1(SUFQ, V, T)                                 \
  NEON_EMU_SI V vld1##SUFQ(const T* p) {                         \
    V r;                                                         \
    memcpy(&r, p, sizeof(V));                                    \
    return r;                                                    \
  }                                                              \
  NEON_EMU_SI void vst1##SUFQ(T* p, V v) { memcpy(p, &v, sizeof(V)); }
NEON_EMU_LD1(_u8, uint8x8_t, uint8_t)
NEON_EMU_LD1(q_u8, uint8x16_t, uint8_t)
NEON_EMU_LD1(_s8, int8x8_t, int8_t)
NEON_EMU_LD1(q_s8, int8x16_t, int8_t)
NEON_EMU_LD1(_u16, uint16x4_t, uint16_t)
NEON_EMU_LD1(q_u16, uint16x8_t, uint16_t)
NEON_EMU_LD1(_s16, int16x4_t, int16_t)
NEON_EMU_LD1(q_s16, int16x8_t, int16_t)
NEON_EMU_LD1(_u32, uint32x2_t, uint32_t)
NEON_EMU_LD1(q_u32, uint32x4_t, uint32_t)
NEON_EMU_LD1(_s32, int32x2_t, int32_t)
NEON_EMU_LD1(q_s32, int32x4_t, int32_t)
NEON_EMU_LD1(_f32, float32x2_t, float)
NEON_EMU_LD1(q_f32, float32x4_t, float)
#undef NEON_EMU_LD1
NEON_EMU_SI uint32x2_t neon_emu_ld1_lane_u32(const uint32_t* p, uint32x2_t v,
                                             int l) {
  uint32_t x;
  memcpy(&x, p, 4);
  v[l] = x;
  return v;
}
#define vld1_lane_u32(p, v, l) neon_emu_ld1_lane_u32((p), (v), (l))
NEON_EMU_SI uint32x4_t neon_emu_ld1q_lane_u32(const uint32_t* p, uint32x4_t v,
                                              int l) {
  uint32_t x;
  memcpy(&x, p, 4);
  v[l] = x;
  return v;
}
#define vld1q_lane_u32(p, v, l) neon_emu_ld1q_lane_u32((p), (v), (l))
NEON_EMU_SI void neon_emu_st1_lane_u32(uint32_t* p, uint32x2_t v, int l) {
  uint32_t x = v[l];
  memcpy(p, &x, 4);
}
#define vst1_lane_u32(p, v, l) neon_emu_st1_lane_u32((p), (v), (l))
NEON_EMU_SI void neon_emu_st1q_lane_u32(uint32_t* p, uint32x4_t v, int l) {
  uint32_t x = v[l];
  memcpy(p, &x, 4);
}
#define vst1q_lane_u32(p, v, l) neon_emu_st1q_lane_u32((p), (v), (l))

// vld2/3/4 deinterleave, vst2/3/4 interleave
#define NEON_EMU_LDN(K, SUFQ, V, T)                                      \
  NEON_EMU_SI V##x##K##_t vld##K##SUFQ(const T* p) {                     \
    V##x##K##_t r;                                                       \
    const int n = NEON_EMU_LANES(r.val[0]);                              \
    for (int i = 0; i < n; i++) {                                        \
      for (int k = 0; k < K; k++) {                                      \
        T x;                                                             \
        memcpy(&x, p + i * K + k, sizeof(T));                            \
        r.val[k][i] = x;                                                 \
      }                                                                  \
    }                                                                    \
    return r;                                                            \
  }                                                                      \
  NEON_EMU_SI void vst##K##SUFQ(T* p, V##x##K##_t v) {                   \
    const int n = NEON_EMU_LANES(v.val[0]);                              \
    for (int i = 0; i < n; i++) {                                        \
      for (int k = 0; k < K; k++) {                                      \
        T x = v.val[k][i];                                               \
        memcpy(p + i * K + k, &x, sizeof(T));                            \
      }                                                                  \
    }                                                                    \
  }
#define NEON_EMU_LDN_ALL(K)                        \
  NEON_EMU_LDN(K, _u8, uint8x8, uint8_t)           \
  NEON_EMU_LDN(K, q_u8, uint8x16, uint8_t)         \
  NEON_EMU_LDN(K, _s8, int8x8, int8_t)             \
  NEON_EMU_LDN(K, q_s8, int8x16, int8_t)           \
  NEON_EMU_LDN(K, _u16, uint16x4, uint16_t)        \
  NEON_EMU_LDN(K, q_u16, uint16x8, uint16_t)       \
  NEON_EMU_LDN(K, _s16, int16x4, int16_t)          \
  NEON_EMU_LDN(K, q_s16, int16x8, int16_t)         \
  NEON_EMU_LDN(K, _u32, uint32x2, uint32_t)        \
  NEON_EMU_LDN(K, q_u32, uint32x4, uint32_t)       \
  NEON_EMU_LDN(K, _s32, int32x2, int32_t)          \
  NEON_EMU_LDN(K, q_s32, int32x4, int32_t)         \
  NEON_EMU_LDN(K, _f32, float32x2, float)          \
  NEON_EMU_LDN(K, q_f32, float32x4, float)
NEON_EMU_LDN_ALL(2)
NEON_EMU_LDN_ALL(3)
NEON_EMU_LDN_ALL(4)
#undef NEON_EMU_LDN_ALL
#undef NEON_EMU_LDN

// widen / narrow
#define NEON_EMU_CONVERT(R, a)                     \
  ({                                               \
    R r_;                                          \
    for (int i = 0; i < NEON_EMU_LANES(r_); i++) { \
      r_[i] = (a)[i];                              \
    }                                              \
    r_;                                            \
  })
NEON_EMU_SI uint16x8_t vmovl_u8(uint8x8_t a) { return NEON_EMU_CONVERT(uint16x8_t, a); }
NEON_EMU_SI uint32x4_t vmovl_u16(uint16x4_t a) { return NEON_EMU_CONVERT(uint32x4_t, a); }
NEON_EMU_SI int16x8_t vmovl_s8(int8x8_t a) { return NEON_EMU_CONVERT(int16x8_t, a); }
NEON_EMU_SI int32x4_t vmovl_s16(int16x4_t a) { return NEON_EMU_CONVERT(int32x4_t, a); }
NEON_EMU_SI uint8x8_t vmovn_u16(uint16x8_t a) { return NEON_EMU_CONVERT(uint8x8_t, a); }
NEON_EMU_SI uint16x4_t vmovn_u32(uint32x4_t a) { return NEON_EMU_CONVERT(uint16x4_t, a); }
NEON_EMU_SI uint32x2_t vmovn_u64(uint64x2_t a) { return NEON_EMU_CONVERT(uint32x2_t, a); }
NEON_EMU_SI uint8x8_t vqmovn_u16(uint16x8_t a) {
  return NEON_EMU_MAP1(uint8x8_t, a, a[i] > 0xff ? 0xff : a[i]);
}
NEON_EMU_SI uint16x4_t vqmovn_u32(uint32x4_t a) {
  return NEON_EMU_MAP1(uint16x4_t, a, a[i] > 0xffff ? 0xffff : a[i]);
}
NEON_EMU_SI uint8x8_t vqmovun_s16(int16x8_t a) {
  return NEON_EMU_MAP1(uint8x8_t, a, a[i] < 0 ? 0 : a[i] > 0xff ? 0xff : a[i]);
}
NEON_EMU_SI int16x4_t vqmovn_s32(int32x4_t a) {
  return NEON_EMU_MAP1(int16x4_t, a,
                       a[i] < -32768 ? -32768 : a[i] > 32767 ? 32767 : a[i]);
}
NEON_EMU_SI uint16x4_t vqmovun_s32(int32x4_t a) {
  return NEON_EMU_MAP1(uint16x4_t, a, a[i] < 0 ? 0 : a[i] > 0xffff ? 0xffff : a[i]);
}
NEON_EMU_SI uint16x8_t vaddw_u8(uint16x8_t a, uint8x8_t b) {
  return a + vmovl_u8(b);
}
NEON_EMU_SI uint16x8_t vsubw_u8(uint16x8_t a, uint8x8_t b) {
  return a - vmovl_u8(b);
}
NEON_EMU_SI uint16x8_t vaddl_u8(uint8x8_t a, uint8x8_t b) {
  return vmovl_u8(a) + vmovl_u8(b);
}
NEON_EMU_SI uint16x8_t vsubl_u8(uint8x8_t a, uint8x8_t b) {
  return vmovl_u8(a) - vmovl_u8(b);
}
NEON_EMU_SI uint16x8_t vmull_u8(uint8x8_t a, uint8x8_t b) {
  return vmovl_u8(a) * vmovl_u8(b);
}
NEON_EMU_SI uint32x4_t vmull_u16(uint16x4_t a, uint16x4_t b) {
  return vmovl_u16(a) * vmovl_u16(b);
}
NEON_EMU_SI int32x4_t vmull_s16(int16x4_t a, int16x4_t b) {
  return vmovl_s16(a) * vmovl_s16(b);
}
NEON_EMU_SI uint64x2_t vmull_n_u32(uint32x2_t a, uint32_t b) {
  uint64x2_t r;
  r[0] = (uint64_t)a[0] * b;
  r[1] = (uint64_t)a[1] * b;
  return r;
}
NEON_EMU_SI uint16x8_t vmlal_u8(uint16x8_t a, uint8x8_t b, uint8x8_t c) {
  return a + vmull_u8(b, c);
}
NEON_EMU_SI uint32x4_t vmlal_u16(uint32x4_t a, uint16x4_t b, uint16x4_t c) {
  return a + vmull_u16(b, c);
}

// shifts (the shift count is an immediate on ARM; any count in range here)
#define NEON_EMU_SHIFTS(SUF, V, W)                                             \
  NEON_EMU_SI V vshr_n_##SUF(V a, int n) { return a >> n; }                    \
  NEON_EMU_SI V vshl_n_##SUF(V a, int n) { return a << n; }                    \
  NEON_EMU_SI V vsra_n_##SUF(V a, V b, int n) { return a + (b >> n); }         \
  NEON_EMU_SI V vrshr_n_##SUF(V a, int n) {                                    \
    return NEON_EMU_MAP1(V, a, (((W)a[i] + ((W)1 << (n - 1))) >> n));          \
  }                                                                            \
  NEON_EMU_SI V vrsra_n_##SUF(V a, V b, int n) { return a + vrshr_n_##SUF(b, n); }
#define NEON_EMU_SHIFTSQ(SUF, V, W)                                            \
  NEON_EMU_SI V vshrq_n_##SUF(V a, int n) { return a >> n; }                   \
  NEON_EMU_SI V vshlq_n_##SUF(V a, int n) { return a << n; }                   \
  NEON_EMU_SI V vsraq_n_##SUF(V a, V b, int n) { return a + (b >> n); }        \
  NEON_EMU_SI V vrshrq_n_##SUF(V a, int n) {                                   \
    return NEON_EMU_MAP1(V, a, (((W)a[i] + ((W)1 << (n - 1))) >> n));          \
  }                                                                            \
  NEON_EMU_SI V vrsraq_n_##SUF(V a, V b, int n) { return a + vrshrq_n_##SUF(b, n); }
NEON_EMU_SHIFTS(u8, uint8x8_t, uint32_t)
NEON_EMU_SHIFTS(u16, uint16x4_t, uint32_t)
NEON_EMU_SHIFTS(s16, int16x4_t, int32_t)
NEON_EMU_SHIFTS(u32, uint32x2_t, uint64_t)
NEON_EMU_SHIFTSQ(u8, uint8x16_t, uint32_t)
NEON_EMU_SHIFTSQ(u16, uint16x8_t, uint32_t)
NEON_EMU_SHIFTSQ(s16, int16x8_t, int32_t)
NEON_EMU_SHIFTSQ(u32, uint32x4_t, uint64_t)
NEON_EMU_SHIFTSQ(s32, int32x4_t, int64_t)
#undef NEON_EMU_SHIFTS
#undef NEON_EMU_SHIFTSQ
NEON_EMU_SI uint8x8_t vshrn_n_u16(uint16x8_t a, int n) {
  return NEON_EMU_MAP1(uint8x8_t, a, (uint8_t)(a[i] >> n));
}
NEON_EMU_SI uint16x4_t vshrn_n_u32(uint32x4_t a, int n) {
  return NEON_EMU_MAP1(uint16x4_t, a, (uint16_t)(a[i] >> n));
}
NEON_EMU_SI uint32x2_t vshrn_n_u64(uint64x2_t a, int n) {
  return NEON_EMU_MAP1(uint32x2_t, a, (uint32_t)(a[i] >> n));
}
NEON_EMU_SI uint8x8_t vrshrn_n_u16(uint16x8_t a, int n) {
  return NEON_EMU_MAP1(uint8x8_t, a,
                       (uint8_t)(((uint32_t)a[i] + (1u << (n - 1))) >> n));
}
NEON_EMU_SI uint8x8_t vqrshrn_n_u16(uint16x8_t a, int n) {
  return NEON_EMU_MAP1(uint8x8_t, a, ({
    uint32_t v_ = ((uint32_t)a[i] + (1u << (n - 1))) >> n;
    (uint8_t)(v_ > 0xff ? 0xff : v_);
  }));
}
NEON_EMU_SI uint8x8_t vqshrun_n_s16(int16x8_t a, int n) {
  return NEON_EMU_MAP1(uint8x8_t, a, ({
    int32_t v_ = (int32_t)a[i] >> n;
    (uint8_t)(v_ < 0 ? 0 : v_ > 0xff ? 0xff : v_);
  }));
}
// RADDHN: (a + b + 2^(n-1)) >> n in the wide lane's width, high half.
NEON_EMU_SI uint8x8_t vraddhn_u16(uint16x8_t a, uint16x8_t b) {
  return NEON_EMU_MAP1(uint8x8_t, a,
                       (uint8_t)(((uint16_t)(a[i] + b[i] + 0x80u)) >> 8));
}
NEON_EMU_SI uint8x8_t vaddhn_u16(uint16x8_t a, uint16x8_t b) {
  return NEON_EMU_MAP1(uint8x8_t, a, (uint8_t)(((uint16_t)(a[i] + b[i])) >> 8));
}

// arithmetic
#define NEON_EMU_ARITH(SUF, V)                                   \
  NEON_EMU_SI V vadd_##SUF(V a, V b) { return a + b; }           \
  NEON_EMU_SI V vsub_##SUF(V a, V b) { return a - b; }           \
  NEON_EMU_SI V vmul_##SUF(V a, V b) { return a * b; }           \
  NEON_EMU_SI V vmla_##SUF(V a, V b, V c) { return a + b * c; }  \
  NEON_EMU_SI V vmls_##SUF(V a, V b, V c) { return a - b * c; }  \
  NEON_EMU_SI V vand_##SUF(V a, V b) { return a & b; }           \
  NEON_EMU_SI V vorr_##SUF(V a, V b) { return a | b; }           \
  NEON_EMU_SI V veor_##SUF(V a, V b) { return a ^ b; }           \
  NEON_EMU_SI V vmvn_##SUF(V a) { return ~a; }
#define NEON_EMU_ARITHQ(SUF, V)                                  \
  NEON_EMU_SI V vaddq_##SUF(V a, V b) { return a + b; }          \
  NEON_EMU_SI V vsubq_##SUF(V a, V b) { return a - b; }          \
  NEON_EMU_SI V vmulq_##SUF(V a, V b) { return a * b; }          \
  NEON_EMU_SI V vmlaq_##SUF(V a, V b, V c) { return a + b * c; } \
  NEON_EMU_SI V vmlsq_##SUF(V a, V b, V c) { return a - b * c; } \
  NEON_EMU_SI V vandq_##SUF(V a, V b) { return a & b; }          \
  NEON_EMU_SI V vorrq_##SUF(V a, V b) { return a | b; }          \
  NEON_EMU_SI V veorq_##SUF(V a, V b) { return a ^ b; }          \
  NEON_EMU_SI V vmvnq_##SUF(V a) { return ~a; }
NEON_EMU_ARITH(u8, uint8x8_t)
NEON_EMU_ARITH(u16, uint16x4_t)
NEON_EMU_ARITH(s16, int16x4_t)
NEON_EMU_ARITH(u32, uint32x2_t)
NEON_EMU_ARITHQ(u8, uint8x16_t)
NEON_EMU_ARITHQ(u16, uint16x8_t)
NEON_EMU_ARITHQ(s16, int16x8_t)
NEON_EMU_ARITHQ(u32, uint32x4_t)
NEON_EMU_ARITHQ(s32, int32x4_t)
#undef NEON_EMU_ARITH
#undef NEON_EMU_ARITHQ
NEON_EMU_SI uint16x8_t vmulq_n_u16(uint16x8_t a, uint16_t b) { return a * b; }
NEON_EMU_SI uint16x4_t vmul_n_u16(uint16x4_t a, uint16_t b) { return a * b; }
NEON_EMU_SI uint16x8_t vmlaq_n_u16(uint16x8_t a, uint16x8_t b, uint16_t c) {
  return a + b * c;
}
NEON_EMU_SI int32x4_t vabsq_s32(int32x4_t a) {
  return NEON_EMU_MAP1(int32x4_t, a,
                       (int32_t)(a[i] < 0 ? 0u - (uint32_t)a[i] : (uint32_t)a[i]));
}
NEON_EMU_SI uint8x8_t vqadd_u8(uint8x8_t a, uint8x8_t b) {
  return NEON_EMU_MAP1(uint8x8_t, a,
                       (uint8_t)(a[i] + b[i] > 0xff ? 0xff : a[i] + b[i]));
}
NEON_EMU_SI uint8x16_t vqaddq_u8(uint8x16_t a, uint8x16_t b) {
  return NEON_EMU_MAP1(uint8x16_t, a,
                       (uint8_t)(a[i] + b[i] > 0xff ? 0xff : a[i] + b[i]));
}
NEON_EMU_SI uint8x8_t vqsub_u8(uint8x8_t a, uint8x8_t b) {
  return NEON_EMU_MAP1(uint8x8_t, a, (uint8_t)(a[i] > b[i] ? a[i] - b[i] : 0));
}
NEON_EMU_SI uint8x16_t vqsubq_u8(uint8x16_t a, uint8x16_t b) {
  return NEON_EMU_MAP1(uint8x16_t, a, (uint8_t)(a[i] > b[i] ? a[i] - b[i] : 0));
}
// SQRDMULH: saturate((2*a*b + 2^15) >> 16)
NEON_EMU_SI int16x8_t vqrdmulhq_s16(int16x8_t a, int16x8_t b) {
  return NEON_EMU_MAP1(int16x8_t, a, ({
    int64_t p_ = (2 * (int64_t)a[i] * b[i] + (1 << 15)) >> 16;
    (int16_t)(p_ > 32767 ? 32767 : p_ < -32768 ? -32768 : p_);
  }));
}
NEON_EMU_SI int16x8_t vqrdmulhq_n_s16(int16x8_t a, int16_t b) {
  return vqrdmulhq_s16(a, (int16x8_t)b);
}

// compare (all-ones lanes)
#define NEON_EMU_CMP(NAME, OP, R, V)                               \
  NEON_EMU_SI R NAME(V a, V b) {                                   \
    return NEON_EMU_MAP1(R, a, (a[i] OP b[i]) ? ~(__typeof__(r_[0]))0 : 0); \
  }
NEON_EMU_CMP(vcleq_u16, <=, uint16x8_t, uint16x8_t)
NEON_EMU_CMP(vcltq_u16, <, uint16x8_t, uint16x8_t)
NEON_EMU_CMP(vcgeq_u16, >=, uint16x8_t, uint16x8_t)
NEON_EMU_CMP(vcgtq_u16, >, uint16x8_t, uint16x8_t)
NEON_EMU_CMP(vceqq_u16, ==, uint16x8_t, uint16x8_t)
NEON_EMU_CMP(vceqq_u8, ==, uint8x16_t, uint8x16_t)
NEON_EMU_CMP(vceqq_u32, ==, uint32x4_t, uint32x4_t)
NEON_EMU_CMP(vcgtq_s32, >, uint32x4_t, int32x4_t)
NEON_EMU_CMP(vcltq_s32, <, uint32x4_t, int32x4_t)
NEON_EMU_CMP(vcgtq_f32, >, uint32x4_t, float32x4_t)
NEON_EMU_CMP(vcltq_f32, <, uint32x4_t, float32x4_t)
NEON_EMU_CMP(vcgeq_f32, >=, uint32x4_t, float32x4_t)
NEON_EMU_CMP(vcleq_f32, <=, uint32x4_t, float32x4_t)
#undef NEON_EMU_CMP

// select
#define NEON_EMU_BSL(NAME, M, V)                     \
  NEON_EMU_SI V NAME(M m, V a, V b) {                \
    M ua = NEON_EMU_BITCAST(M, a), ub = NEON_EMU_BITCAST(M, b); \
    M r = (m & ua) | (~m & ub);                      \
    return NEON_EMU_BITCAST(V, r);                   \
  }
NEON_EMU_BSL(vbslq_u8, uint8x16_t, uint8x16_t)
NEON_EMU_BSL(vbsl_u8, uint8x8_t, uint8x8_t)
NEON_EMU_BSL(vbslq_u16, uint16x8_t, uint16x8_t)
NEON_EMU_BSL(vbslq_u32, uint32x4_t, uint32x4_t)
NEON_EMU_BSL(vbslq_s32, uint32x4_t, int32x4_t)
#undef NEON_EMU_BSL

// min / max and across-vector reductions
#define NEON_EMU_MINMAX(SUF, V)                                          \
  NEON_EMU_SI V vminq_##SUF(V a, V b) {                                  \
    return NEON_EMU_MAP1(V, a, a[i] < b[i] ? a[i] : b[i]);               \
  }                                                                      \
  NEON_EMU_SI V vmaxq_##SUF(V a, V b) {                                  \
    return NEON_EMU_MAP1(V, a, a[i] > b[i] ? a[i] : b[i]);               \
  }
NEON_EMU_MINMAX(u8, uint8x16_t)
NEON_EMU_MINMAX(u16, uint16x8_t)
NEON_EMU_MINMAX(u32, uint32x4_t)
NEON_EMU_MINMAX(s16, int16x8_t)
NEON_EMU_MINMAX(s32, int32x4_t)
#undef NEON_EMU_MINMAX
NEON_EMU_SI uint8x8_t vmin_u8(uint8x8_t a, uint8x8_t b) {
  return NEON_EMU_MAP1(uint8x8_t, a, a[i] < b[i] ? a[i] : b[i]);
}
NEON_EMU_SI uint8x8_t vmax_u8(uint8x8_t a, uint8x8_t b) {
  return NEON_EMU_MAP1(uint8x8_t, a, a[i] > b[i] ? a[i] : b[i]);
}
#define NEON_EMU_REDUCE(NAME, V, T, OP)               \
  NEON_EMU_SI T NAME(V a) {                           \
    T r = a[0];                                       \
    for (int i = 1; i < NEON_EMU_LANES(a); i++) {     \
      r = (a[i] OP r) ? a[i] : r;                     \
    }                                                 \
    return r;                                         \
  }
NEON_EMU_REDUCE(vminv_u8, uint8x8_t, uint8_t, <)
NEON_EMU_REDUCE(vminvq_u8, uint8x16_t, uint8_t, <)
NEON_EMU_REDUCE(vminv_u16, uint16x4_t, uint16_t, <)
NEON_EMU_REDUCE(vminvq_u16, uint16x8_t, uint16_t, <)
NEON_EMU_REDUCE(vminv_u32, uint32x2_t, uint32_t, <)
NEON_EMU_REDUCE(vminvq_u32, uint32x4_t, uint32_t, <)
NEON_EMU_REDUCE(vmaxv_u8, uint8x8_t, uint8_t, >)
NEON_EMU_REDUCE(vmaxvq_u8, uint8x16_t, uint8_t, >)
NEON_EMU_REDUCE(vmaxvq_u16, uint16x8_t, uint16_t, >)
NEON_EMU_REDUCE(vmaxvq_u32, uint32x4_t, uint32_t, >)
#undef NEON_EMU_REDUCE

// table lookup: an index past the table gives 0.
NEON_EMU_SI uint8x8_t vtbl1_u8(uint8x8_t t, uint8x8_t idx) {
  return NEON_EMU_MAP1(uint8x8_t, t, (uint8_t)(idx[i] < 8 ? t[idx[i]] : 0));
}
NEON_EMU_SI uint8x16_t vqtbl1q_u8(uint8x16_t t, uint8x16_t idx) {
  return NEON_EMU_MAP1(uint8x16_t, t, (uint8_t)(idx[i] < 16 ? t[idx[i]] : 0));
}
NEON_EMU_SI uint8x8_t vqtbl1_u8(uint8x16_t t, uint8x8_t idx) {
  return NEON_EMU_MAP1(uint8x8_t, idx, (uint8_t)(idx[i] < 16 ? t[idx[i]] : 0));
}
NEON_EMU_SI uint8x16_t vrev32q_u8(uint8x16_t a) {
  return NEON_EMU_MAP1(uint8x16_t, a, a[(i & ~3) | (3 - (i & 3))]);
}
NEON_EMU_SI uint8x8_t vrev32_u8(uint8x8_t a) {
  return NEON_EMU_MAP1(uint8x8_t, a, a[(i & ~3) | (3 - (i & 3))]);
}

#undef NEON_EMU_MAP1
#endif  // SkNeonEmu_DEFINED
