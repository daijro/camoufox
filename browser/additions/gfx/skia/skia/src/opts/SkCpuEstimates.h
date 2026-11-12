/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * RCPPS and RSQRTPS as another x86 vendor's CPU computes them.
 *
 * The two estimate instructions are specified only to a relative error of
 * 1.5 * 2^-12, and Intel and AMD implement them with different tables: the
 * same input gives different bits on the two vendors, and the same bits on
 * every generation of one vendor (Intel 11th and 12th gen, AMD Zen 4 and
 * Zen 5 agree over all 2^32 inputs). Skia's raster pipeline uses them for
 * blend modes, perspective and matrix inversion, so a canvas a page reads back
 * shows which vendor drew it.
 *
 * A table holds the instruction's output for inputs 1.m (rcp) and for inputs
 * 1.m and 2.m (rsqrt), indexed by the top 12 mantissa bits; the output's
 * mantissa does not depend on the input's exponent. Intel's outputs depend on
 * fewer bits (11 for rcp, 10 for rsqrt) and its table repeats them. With the
 * recorded tables (SkCpuEstimateTables.h) these functions reproduce both
 * vendors' instructions for every input, special values included;
 * browser/tests/cpu-estimates/check.py runs that comparison.
 *
 * Plain C, so the check compiles exactly this code.
 */

#ifndef SkCpuEstimates_DEFINED
#define SkCpuEstimates_DEFINED

#include <stdint.h>

#define SK_CPU_ESTIMATE_BITS 12
#define SK_CPU_ESTIMATE_ENTRIES (1 << SK_CPU_ESTIMATE_BITS)
/* rcp[4096], rsqrt of 1.m[4096], rsqrt of 2.m[4096] */
#define SK_CPU_ESTIMATE_TABLE_SIZE (3 * SK_CPU_ESTIMATE_ENTRIES)

enum {
  SK_CPU_VENDOR_HOST = 0,
  SK_CPU_VENDOR_INTEL = 1,
  SK_CPU_VENDOR_AMD = 2,
  SK_CPU_IDENTITY_ARM64 = 3,
};

static inline uint32_t sk_cpu_estimate_rcp(const uint32_t* table, uint32_t b) {
  uint32_t s = b & 0x80000000u, e = (b >> 23) & 0xff;
  if (e == 0xff) {
    return (b & 0x7fffff) ? (b | 0x400000u) : s; /* NaN is quieted, 1/inf is 0 */
  }
  if (e == 0) {
    return s | 0x7f800000u; /* zero and denormals give infinity */
  }
  uint32_t t = table[(b & 0x7fffff) >> (23 - SK_CPU_ESTIMATE_BITS)];
  int oe = (int)((t >> 23) & 0xff) + 127 - (int)e;
  if (oe <= 0) {
    return s; /* a result below the normal range is flushed to 0 */
  }
  return s | ((uint32_t)oe << 23) | (t & 0x7fffff);
}

static inline uint32_t sk_cpu_estimate_rsqrt(const uint32_t* table, uint32_t b) {
  uint32_t s = b & 0x80000000u, e = (b >> 23) & 0xff;
  if (e == 0xff) {
    return (b & 0x7fffff) ? (b | 0x400000u) : (s ? 0xffc00000u : 0);
  }
  if (e == 0) {
    return s | 0x7f800000u;
  }
  if (s) {
    return 0xffc00000u; /* a negative input gives the default NaN */
  }
  int p = ((int)e - 127) & 1;
  uint32_t t = table[(1 + p) * SK_CPU_ESTIMATE_ENTRIES +
                     ((b & 0x7fffff) >> (23 - SK_CPU_ESTIMATE_BITS))];
  int oe = (int)((t >> 23) & 0xff) - (((int)e - 127 - p) / 2);
  return ((uint32_t)oe << 23) | (t & 0x7fffff);
}

#ifdef __cplusplus
/* The recorded table of the vendor general.cpu_identity names, or
 * nullptr when the native instruction already gives that vendor's bits: the
 * pref is 0, or names the CPU this runs on (SkCpuEstimates_mozilla.cpp). */
const uint32_t* sk_cpu_estimates();

/* Whether general.cpu_identity names an ARM64 machine on this x86-64 one:
 * the opts tiers then switch to Skia's AArch64 code, built against
 * SkNeonEmu.h (the _neonemu.cpp files). */
bool sk_cpu_emulates_arm64();
#endif

#endif
