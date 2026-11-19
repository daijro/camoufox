/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * x86 SIMD intrinsics on AArch64, bit for bit as an x86-64 CPU computes them,
 * for general.cpu_identity = Intel or AMD on an ARM64 host. The directory
 * stands in for the compiler's <immintrin.h> family, so x86 code paths
 * (Skia, libopus, speex) build unchanged and run the x86 arithmetic.
 *
 * SIMDe gives x86 results for every intrinsic these libraries use except
 * where AArch64's own float rules show through, which this file overrides:
 * an invalid operation (inf - inf, 0 * inf, sqrt(-1)) gives x86's negative
 * default NaN where AArch64 gives a positive one; a NaN operand propagates
 * by x86's operand order; and a float-to-int conversion out of range gives
 * 0x80000000 where AArch64 saturates. Estimates (rcp, rsqrt) are not
 * emulated here: their callers use the recorded vendor tables.
 */

#ifndef X86EMU_H_
#define X86EMU_H_

#if !defined(__aarch64__)
#  error x86emu is the AArch64 build of x86 code
#endif

#define SIMDE_ENABLE_NATIVE_ALIASES
#include "simde/x86/avx2.h"
#include "simde/x86/fma.h"
#include "simde/x86/f16c.h"

#include <arm_neon.h>

#define X86EMU_INLINE static inline __attribute__((always_inline))

/* x86's NaN rules for an operation whose AArch64 result is r: the first NaN
 * operand, quieted; else x86's default NaN for an invalid operation. FMA
 * takes the multiplicands first. */
X86EMU_INLINE uint32x4_t x86emu_nan_pick(uint32x4_t out, float32x4_t x) {
  return vbslq_u32(vmvnq_u32(vceqq_f32(x, x)),
                   vorrq_u32(vreinterpretq_u32_f32(x), vdupq_n_u32(0x00400000)),
                   out);
}

X86EMU_INLINE uint32x4_t x86emu_nan_default(float32x4_t r) {
  return vbslq_u32(vmvnq_u32(vceqq_f32(r, r)), vdupq_n_u32(0xffc00000),
                   vreinterpretq_u32_f32(r));
}

X86EMU_INLINE float32x4_t x86emu_nan2(float32x4_t r, float32x4_t a,
                                      float32x4_t b) {
  return vreinterpretq_f32_u32(
      x86emu_nan_pick(x86emu_nan_pick(x86emu_nan_default(r), b), a));
}

X86EMU_INLINE float32x4_t x86emu_nan3(float32x4_t r, float32x4_t a,
                                      float32x4_t b, float32x4_t c) {
  return vreinterpretq_f32_u32(x86emu_nan_pick(
      x86emu_nan_pick(x86emu_nan_pick(x86emu_nan_default(r), c), b), a));
}

/* An out-of-range or NaN input converts to x86's "integer indefinite". */
X86EMU_INLINE int32x4_t x86emu_cvt_range(float32x4_t a, int32x4_t r) {
  uint32x4_t ok = vandq_u32(vcltq_f32(a, vdupq_n_f32(2147483648.0f)),
                            vcgeq_f32(a, vdupq_n_f32(-2147483648.0f)));
  return vbslq_s32(ok, r, vdupq_n_s32(INT32_MIN));
}

#define X86EMU_F(x) simde__m128_to_neon_f32(x)
#define X86EMU_M(x) simde__m128_from_neon_f32(x)

X86EMU_INLINE __m128 x86emu_add_ps(__m128 a, __m128 b) {
  return X86EMU_M(x86emu_nan2(vaddq_f32(X86EMU_F(a), X86EMU_F(b)), X86EMU_F(a), X86EMU_F(b)));
}
X86EMU_INLINE __m128 x86emu_sub_ps(__m128 a, __m128 b) {
  return X86EMU_M(x86emu_nan2(vsubq_f32(X86EMU_F(a), X86EMU_F(b)), X86EMU_F(a), X86EMU_F(b)));
}
X86EMU_INLINE __m128 x86emu_mul_ps(__m128 a, __m128 b) {
  return X86EMU_M(x86emu_nan2(vmulq_f32(X86EMU_F(a), X86EMU_F(b)), X86EMU_F(a), X86EMU_F(b)));
}
X86EMU_INLINE __m128 x86emu_div_ps(__m128 a, __m128 b) {
  return X86EMU_M(x86emu_nan2(vdivq_f32(X86EMU_F(a), X86EMU_F(b)), X86EMU_F(a), X86EMU_F(b)));
}
X86EMU_INLINE __m128 x86emu_sqrt_ps(__m128 a) {
  return X86EMU_M(x86emu_nan2(vsqrtq_f32(X86EMU_F(a)), X86EMU_F(a), X86EMU_F(a)));
}
X86EMU_INLINE __m128 x86emu_hadd_ps(__m128 a, __m128 b) {
  float32x4_t even = vuzp1q_f32(X86EMU_F(a), X86EMU_F(b));
  float32x4_t odd = vuzp2q_f32(X86EMU_F(a), X86EMU_F(b));
  return X86EMU_M(x86emu_nan2(vaddq_f32(even, odd), even, odd));
}
X86EMU_INLINE __m128 x86emu_hsub_ps(__m128 a, __m128 b) {
  float32x4_t even = vuzp1q_f32(X86EMU_F(a), X86EMU_F(b));
  float32x4_t odd = vuzp2q_f32(X86EMU_F(a), X86EMU_F(b));
  return X86EMU_M(x86emu_nan2(vsubq_f32(even, odd), even, odd));
}
X86EMU_INLINE __m128 x86emu_addsub_ps(__m128 a, __m128 b) {
  float32x4_t sum = X86EMU_F(x86emu_add_ps(a, b));
  float32x4_t diff = X86EMU_F(x86emu_sub_ps(a, b));
  return X86EMU_M(vtrn2q_f32(vtrn1q_f32(diff, diff), sum));
}
X86EMU_INLINE __m128 x86emu_fmadd_ps(__m128 a, __m128 b, __m128 c) {
  float32x4_t fa = X86EMU_F(a), fb = X86EMU_F(b), fc = X86EMU_F(c);
  return X86EMU_M(x86emu_nan3(vfmaq_f32(fc, fa, fb), fa, fb, fc));
}
X86EMU_INLINE __m128 x86emu_fmsub_ps(__m128 a, __m128 b, __m128 c) {
  float32x4_t fa = X86EMU_F(a), fb = X86EMU_F(b), fc = X86EMU_F(c);
  return X86EMU_M(x86emu_nan3(vfmaq_f32(vnegq_f32(fc), fa, fb), fa, fb, fc));
}
X86EMU_INLINE __m128 x86emu_fnmadd_ps(__m128 a, __m128 b, __m128 c) {
  float32x4_t fa = X86EMU_F(a), fb = X86EMU_F(b), fc = X86EMU_F(c);
  return X86EMU_M(x86emu_nan3(vfmsq_f32(fc, fa, fb), fa, fb, fc));
}
X86EMU_INLINE __m128 x86emu_fnmsub_ps(__m128 a, __m128 b, __m128 c) {
  float32x4_t fa = X86EMU_F(a), fb = X86EMU_F(b), fc = X86EMU_F(c);
  return X86EMU_M(x86emu_nan3(vnegq_f32(vfmaq_f32(fc, fa, fb)), fa, fb, fc));
}
X86EMU_INLINE __m128i x86emu_cvtps_epi32(__m128 a) {
  float32x4_t fa = X86EMU_F(a);
  return simde__m128i_from_neon_i32(x86emu_cvt_range(fa, vcvtnq_s32_f32(fa)));
}
X86EMU_INLINE __m128i x86emu_cvttps_epi32(__m128 a) {
  float32x4_t fa = X86EMU_F(a);
  return simde__m128i_from_neon_i32(x86emu_cvt_range(fa, vcvtq_s32_f32(fa)));
}
X86EMU_INLINE int x86emu_cvtss_si32(__m128 a) {
  return vgetq_lane_s32(simde__m128i_to_neon_i32(x86emu_cvtps_epi32(a)), 0);
}
X86EMU_INLINE int x86emu_cvttss_si32(__m128 a) {
  return vgetq_lane_s32(simde__m128i_to_neon_i32(x86emu_cvttps_epi32(a)), 0);
}
/* AArch64's own conversion quiets a signaling NaN as x86 does. */
X86EMU_INLINE __m128 x86emu_cvtph_ps(__m128i a) {
  return X86EMU_M(vcvt_f32_f16(vreinterpret_f16_s64(vget_low_s64(simde__m128i_to_neon_i64(a)))));
}

/* The scalar forms work on element 0 and pass a's others through. */
#define X86EMU_SS(name)                                         \
  X86EMU_INLINE __m128 x86emu_##name##_ss(__m128 a, __m128 b) { \
    return X86EMU_M(vcopyq_laneq_f32(                           \
        X86EMU_F(a), 0, X86EMU_F(x86emu_##name##_ps(a, b)), 0)); \
  }
X86EMU_SS(add)
X86EMU_SS(sub)
X86EMU_SS(mul)
X86EMU_SS(div)
#undef X86EMU_SS

/* A 256-bit operation is two 128-bit halves. */
#define X86EMU_256_2(name)                                               \
  X86EMU_INLINE __m256 x86emu_mm256_##name(__m256 a, __m256 b) {         \
    simde__m256_private a_ = simde__m256_to_private(a),                  \
                        b_ = simde__m256_to_private(b), r_;              \
    r_.m128[0] = x86emu_##name(a_.m128[0], b_.m128[0]);                  \
    r_.m128[1] = x86emu_##name(a_.m128[1], b_.m128[1]);                  \
    return simde__m256_from_private(r_);                                 \
  }
#define X86EMU_256_3(name)                                                   \
  X86EMU_INLINE __m256 x86emu_mm256_##name(__m256 a, __m256 b, __m256 c) {   \
    simde__m256_private a_ = simde__m256_to_private(a),                      \
                        b_ = simde__m256_to_private(b),                      \
                        c_ = simde__m256_to_private(c), r_;                  \
    r_.m128[0] = x86emu_##name(a_.m128[0], b_.m128[0], c_.m128[0]);          \
    r_.m128[1] = x86emu_##name(a_.m128[1], b_.m128[1], c_.m128[1]);          \
    return simde__m256_from_private(r_);                                     \
  }
X86EMU_256_2(add_ps)
X86EMU_256_2(sub_ps)
X86EMU_256_2(mul_ps)
X86EMU_256_2(div_ps)
X86EMU_256_2(hadd_ps)
X86EMU_256_2(hsub_ps)
X86EMU_256_2(addsub_ps)
X86EMU_256_3(fmadd_ps)
X86EMU_256_3(fmsub_ps)
X86EMU_256_3(fnmadd_ps)
X86EMU_256_3(fnmsub_ps)
X86EMU_INLINE __m256 x86emu_mm256_sqrt_ps(__m256 a) {
  simde__m256_private a_ = simde__m256_to_private(a), r_;
  r_.m128[0] = x86emu_sqrt_ps(a_.m128[0]);
  r_.m128[1] = x86emu_sqrt_ps(a_.m128[1]);
  return simde__m256_from_private(r_);
}
X86EMU_INLINE __m256i x86emu_mm256_cvtps_epi32(__m256 a) {
  simde__m256_private a_ = simde__m256_to_private(a);
  simde__m256i_private r_;
  r_.m128i[0] = x86emu_cvtps_epi32(a_.m128[0]);
  r_.m128i[1] = x86emu_cvtps_epi32(a_.m128[1]);
  return simde__m256i_from_private(r_);
}
X86EMU_INLINE __m256i x86emu_mm256_cvttps_epi32(__m256 a) {
  simde__m256_private a_ = simde__m256_to_private(a);
  simde__m256i_private r_;
  r_.m128i[0] = x86emu_cvttps_epi32(a_.m128[0]);
  r_.m128i[1] = x86emu_cvttps_epi32(a_.m128[1]);
  return simde__m256i_from_private(r_);
}
X86EMU_INLINE __m256 x86emu_mm256_cvtph_ps(__m128i a) {
  simde__m256_private r_;
  r_.m128[0] = x86emu_cvtph_ps(a);
  r_.m128[1] = x86emu_cvtph_ps(_mm_srli_si128(a, 8));
  return simde__m256_from_private(r_);
}
#undef X86EMU_256_2
#undef X86EMU_256_3

#undef _mm_add_ps
#define _mm_add_ps x86emu_add_ps
#undef _mm_sub_ps
#define _mm_sub_ps x86emu_sub_ps
#undef _mm_mul_ps
#define _mm_mul_ps x86emu_mul_ps
#undef _mm_div_ps
#define _mm_div_ps x86emu_div_ps
#undef _mm_sqrt_ps
#define _mm_sqrt_ps x86emu_sqrt_ps
#undef _mm_add_ss
#define _mm_add_ss x86emu_add_ss
#undef _mm_sub_ss
#define _mm_sub_ss x86emu_sub_ss
#undef _mm_mul_ss
#define _mm_mul_ss x86emu_mul_ss
#undef _mm_div_ss
#define _mm_div_ss x86emu_div_ss
#undef _mm_hadd_ps
#define _mm_hadd_ps x86emu_hadd_ps
#undef _mm_hsub_ps
#define _mm_hsub_ps x86emu_hsub_ps
#undef _mm_addsub_ps
#define _mm_addsub_ps x86emu_addsub_ps
#undef _mm_fmadd_ps
#define _mm_fmadd_ps x86emu_fmadd_ps
#undef _mm_fmsub_ps
#define _mm_fmsub_ps x86emu_fmsub_ps
#undef _mm_fnmadd_ps
#define _mm_fnmadd_ps x86emu_fnmadd_ps
#undef _mm_fnmsub_ps
#define _mm_fnmsub_ps x86emu_fnmsub_ps
#undef _mm_cvtps_epi32
#define _mm_cvtps_epi32 x86emu_cvtps_epi32
#undef _mm_cvttps_epi32
#define _mm_cvttps_epi32 x86emu_cvttps_epi32
#undef _mm_cvtss_si32
#define _mm_cvtss_si32 x86emu_cvtss_si32
#undef _mm_cvt_ss2si
#define _mm_cvt_ss2si x86emu_cvtss_si32
#undef _mm_cvttss_si32
#define _mm_cvttss_si32 x86emu_cvttss_si32
#undef _mm_cvtph_ps
#define _mm_cvtph_ps x86emu_cvtph_ps
#undef _mm256_add_ps
#define _mm256_add_ps x86emu_mm256_add_ps
#undef _mm256_sub_ps
#define _mm256_sub_ps x86emu_mm256_sub_ps
#undef _mm256_mul_ps
#define _mm256_mul_ps x86emu_mm256_mul_ps
#undef _mm256_div_ps
#define _mm256_div_ps x86emu_mm256_div_ps
#undef _mm256_sqrt_ps
#define _mm256_sqrt_ps x86emu_mm256_sqrt_ps
#undef _mm256_hadd_ps
#define _mm256_hadd_ps x86emu_mm256_hadd_ps
#undef _mm256_hsub_ps
#define _mm256_hsub_ps x86emu_mm256_hsub_ps
#undef _mm256_addsub_ps
#define _mm256_addsub_ps x86emu_mm256_addsub_ps
#undef _mm256_fmadd_ps
#define _mm256_fmadd_ps x86emu_mm256_fmadd_ps
#undef _mm256_fmsub_ps
#define _mm256_fmsub_ps x86emu_mm256_fmsub_ps
#undef _mm256_fnmadd_ps
#define _mm256_fnmadd_ps x86emu_mm256_fnmadd_ps
#undef _mm256_fnmsub_ps
#define _mm256_fnmsub_ps x86emu_mm256_fnmsub_ps
#undef _mm256_cvtps_epi32
#define _mm256_cvtps_epi32 x86emu_mm256_cvtps_epi32
#undef _mm256_cvttps_epi32
#define _mm256_cvttps_epi32 x86emu_mm256_cvttps_epi32
#undef _mm256_cvtph_ps
#define _mm256_cvtph_ps x86emu_mm256_cvtph_ps

#endif /* X86EMU_H_ */
