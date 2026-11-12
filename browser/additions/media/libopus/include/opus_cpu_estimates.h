/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * The encoder's PVQ search (celt/x86/vq_sse2.c) uses RCPPS and RSQRTPS, whose
 * bits differ between Intel and AMD CPUs, so the encoded stream shows which
 * vendor encoded it. Like Skia's raster pipeline, it can compute another
 * vendor's bits from a recorded table (gfx/skia/skia/src/opts/SkCpuEstimates.h),
 * chosen by general.cpu_identity.
 *
 * When general.cpu_identity emulates an arm64 CPU, x86 encoders and decoders
 * instead run Firefox aarch64's NEON kernels, ported to C
 * (celt/x86/celt_neonemu.c, celt_tx_neonemu.c).
 *
 * libopus is built into gkcodecs, which cannot read prefs, so Gecko hands it
 * both: opus_mozilla_use_cpu_vendor() before each encoder or decoder is
 * created.
 */

#ifndef OPUS_CPU_ESTIMATES_H
#define OPUS_CPU_ESTIMATES_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The recorded table to reproduce, or NULL for this CPU's own instructions.
 * Defined in gkcodecs: default visibility, which libxul's hidden-by-default
 * build would otherwise not give these declarations (the system-header
 * wrappers do that for opus.h). */
#if defined(__GNUC__)
#  pragma GCC visibility push(default)
#endif
void opus_mozilla_set_cpu_estimates(const uint32_t* table);
const uint32_t* opus_mozilla_cpu_estimates(void);
/* Nonzero: encoders and decoders created from now on run Firefox aarch64's
 * kernels. */
void opus_mozilla_set_emulate_arm64(int on);
int opus_mozilla_emulates_arm64(void);
#if defined(__GNUC__)
#  pragma GCC visibility pop
#endif

#ifdef __cplusplus
}

/* Defined in libxul by gfx/skia/skia/src/ports/SkCpuEstimates_mozilla.cpp. */
const uint32_t* sk_cpu_estimates();
bool sk_cpu_emulates_arm64();

static inline void opus_mozilla_use_cpu_vendor() {
  opus_mozilla_set_cpu_estimates(sk_cpu_estimates());
  opus_mozilla_set_emulate_arm64(sk_cpu_emulates_arm64());
}
#endif

#endif
