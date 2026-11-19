/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* AArch64 Opus kernels for x86, selected as arch OPUS_ARCH_X86_NEONEMU
 * when Gecko emulates an arm64 CPU (general.cpu_identity = 3).
 *
 * Each function reproduces, value for value, what Firefox's aarch64 build
 * computes:
 *   celt_inner_prod / dual_inner_prod  <- celt/arm/pitch_neon_intr.c
 *   celt_pitch_xcorr                   <- celt/arm/celt_neon_intr.c
 *   comb_filter_const                  <- celt/arm/celt_neon_aarch64.S
 *   celt_deemphasis                    <- celt/arm/celt_neon_aarch64.S
 *   deemphasis_stereo_simple           <- celt/arm/celt_neon_aarch64.S
 * The inverse MDCT is celt_tx_neonemu.c, translated from celt_tx_neon.S.
 * aarch64 NEON float lanes are plain IEEE single precision, so a lane is a
 * C float. vmlaq/vmlaq_lane become vfmaq (__ARM_FEATURE_FMA) and are fused:
 * fmaf() here. Everything else in those files is unfused, as is the scalar
 * C they share with x86 (Gecko builds with -ffp-contract=off). The order of
 * every add follows the NEON lane layout, not the C reference. */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <math.h>

#include "x86/celt_neonemu.h"

#if defined(OPUS_X86_NEONEMU)

#pragma STDC FP_CONTRACT OFF

opus_val32 celt_inner_prod_neonemu(const opus_val16 *x, const opus_val16 *y,
      int N)
{
   int i, k;
   float acc[4] = {0, 0, 0, 0};
   float xy;
   for (i = 0; i < N - 7; i += 8) {
      for (k = 0; k < 4; k++) acc[k] = fmaf(x[i + k], y[i + k], acc[k]);
      for (k = 0; k < 4; k++) acc[k] = fmaf(x[i + 4 + k], y[i + 4 + k], acc[k]);
   }
   if (N - i >= 4) {
      for (k = 0; k < 4; k++) acc[k] = fmaf(x[i + k], y[i + k], acc[k]);
      i += 4;
   }
   /* vadd_f32(low, high), then vpadd_f32 */
   xy = (acc[0] + acc[2]) + (acc[1] + acc[3]);
   for (; i < N; i++) {
      xy = xy + x[i] * y[i];
   }
   return xy;
}

void dual_inner_prod_neonemu(const opus_val16 *x, const opus_val16 *y01,
      const opus_val16 *y02, int N, opus_val32 *xy1, opus_val32 *xy2)
{
   *xy1 = celt_inner_prod_neonemu(x, y01, N);
   *xy2 = celt_inner_prod_neonemu(x, y02, N);
}

/* xcorr_kernel_neon_float: lane k accumulates y[j + k] * x[j] with one fused
   multiply-add per j, in order j = 0 .. len - 1, from 0. */
static void xcorr_kernel_neonemu(const float *x, const float *y,
      float sum[4], int len)
{
   int j, k;
   float acc[4] = {0, 0, 0, 0};
   for (j = 0; j < len; j++) {
      for (k = 0; k < 4; k++) acc[k] = fmaf(y[j + k], x[j], acc[k]);
   }
   for (k = 0; k < 4; k++) sum[k] = acc[k];
}

void celt_pitch_xcorr_neonemu(const opus_val16 *_x, const opus_val16 *_y,
      opus_val32 *xcorr, int len, int max_pitch)
{
   int i;
   for (i = 0; i < (max_pitch - 3); i += 4) {
      xcorr_kernel_neonemu(_x, _y + i, xcorr + i, len);
   }
   for (; i < max_pitch; i++) {
      xcorr[i] = celt_inner_prod_neonemu(_x, _y + i, len);
   }
}

/* comb_filter_const_neon: the vector loop and the scalar tail apply the
   taps in the same order, so one scalar loop covers both. T >= 15, so
   in-place filtering (x == y) reads only finished outputs either way. */
void comb_filter_const_neonemu(opus_val32 *y, opus_val32 *x, int T, int N,
      opus_val16 g10, opus_val16 g11, opus_val16 g12)
{
   int i;
   for (i = 0; i < N; i++) {
      const float *xt = x + i - T;
      float acc = xt[-2] * g12;
      acc = fmaf(xt[2], g12, acc);
      acc = fmaf(xt[0], g10, acc);
      acc = fmaf(xt[1] + xt[-1], g11, acc);
      y[i] = x[i] + acc;
   }
}

/* celt_deemphasis_neon: eight samples per step as two 4-lane IIR blocks.
   Unlike celt_deemphasis_c, no VERY_SMALL is added. */
typedef struct {
   float c4[4], c3[4], c2[4], c1[4];   /* v4, v5, v6, v7 */
} deemph_coefs;

static void deemph_setup(deemph_coefs *k, float c)
{
   float c2 = c * c, c3 = c * c2, c4 = c2 * c2;
   k->c4[0] = c;   k->c4[1] = c2;  k->c4[2] = c3;  k->c4[3] = c4;
   k->c3[0] = 0;   k->c3[1] = c;   k->c3[2] = c2;  k->c3[3] = c3;
   k->c2[0] = 0;   k->c2[1] = 0;   k->c2[2] = c;   k->c2[3] = c2;
   k->c1[0] = 0;   k->c1[1] = 0;   k->c1[2] = 0;   k->c1[3] = c;
}

/* v0 = {m, c m, c^2 m, c^3 m} */
static void deemph_prime(const deemph_coefs *k, float m, float v0[4])
{
   int i;
   for (i = 0; i < 4; i++) v0[i] = k->c3[i] * m;
   v0[0] = m;
}

/* One 8-sample step: x[0..7] in, o[0..7] the unscaled output, v0 the
   carried state (lane 0 ends as c * o[7]). */
static void deemph_step(const deemph_coefs *k, const float *x, float o[8],
      float v0[4])
{
   int i;
   float v3[4];
   for (i = 0; i < 4; i++) {
      v0[i] = fmaf(k->c3[i], x[0], v0[i]);
      v3[i] = k->c1[i] * x[6];
      v0[i] = fmaf(k->c2[i], x[1], v0[i]);
      v3[i] = fmaf(k->c2[i], x[5], v3[i]);
      v0[i] = fmaf(k->c1[i], x[2], v0[i]);
      v3[i] = fmaf(k->c3[i], x[4], v3[i]);
   }
   for (i = 0; i < 4; i++) {
      o[i] = x[i] + v0[i];
      o[4 + i] = x[4 + i] + v3[i];
   }
   for (i = 0; i < 4; i++) o[4 + i] = fmaf(k->c4[i], o[3], o[4 + i]);
   for (i = 0; i < 4; i++) v0[i] = k->c4[i] * o[7];
}

static const float deemph_scale = 3.0517578125e-5f;  /* 1 / CELT_SIG_SCALE */

opus_val32 celt_deemphasis_neonemu(opus_res *y, const opus_val32 *x,
      opus_val16 coef, opus_val32 m, int N)
{
   deemph_coefs k;
   float v0[4], o[8];
   int i;
   deemph_setup(&k, coef);
   deemph_prime(&k, m, v0);
   for (; N >= 8; N -= 8, x += 8, y += 8) {
      deemph_step(&k, x, o, v0);
      for (i = 0; i < 8; i++) y[i] = o[i] * deemph_scale;
   }
   m = v0[0];
   for (; N > 0; N--) {
      float t = *x++ + m;
      m = t * k.c4[0];
      *y++ = t * deemph_scale;
   }
   return m;
}

void deemphasis_stereo_simple_neonemu(celt_sig *in[], opus_res *pcm, int N,
      opus_val16 coef, celt_sig *mem)
{
   deemph_coefs k;
   const float *x0 = in[0], *x1 = in[1];
   float a[4], b[4], oa[8], ob[8];
   float m0, m1;
   int i;
   deemph_setup(&k, coef);
   deemph_prime(&k, mem[0], a);
   deemph_prime(&k, mem[1], b);
   for (; N >= 8; N -= 8, x0 += 8, x1 += 8, pcm += 16) {
      deemph_step(&k, x0, oa, a);
      deemph_step(&k, x1, ob, b);
      for (i = 0; i < 8; i++) {
         pcm[2 * i] = oa[i] * deemph_scale;
         pcm[2 * i + 1] = ob[i] * deemph_scale;
      }
   }
   m0 = a[0];
   m1 = b[0];
   for (; N > 0; N--) {
      float t0 = *x0++ + m0;
      float t1 = *x1++ + m1;
      m0 = t0 * k.c4[0];
      m1 = t1 * k.c4[0];
      *pcm++ = t0 * deemph_scale;
      *pcm++ = t1 * deemph_scale;
   }
   mem[0] = m0;
   mem[1] = m1;
}

#endif
