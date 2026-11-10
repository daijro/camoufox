/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * The encoder's PVQ search (celt/x86/vq_sse2.c) uses RCPPS and RSQRTPS, whose
 * bits differ between Intel and AMD CPUs, so the encoded stream shows which
 * vendor encoded it. Like Skia's raster pipeline, it can compute another
 * vendor's bits from a recorded table (gfx/skia/skia/src/opts/SkCpuEstimates.h),
 * chosen by gfx.skia.cpu_vendor_estimates.
 *
 * libopus is built into gkcodecs, which cannot read prefs, so Gecko hands it
 * the table: opus_mozilla_use_cpu_vendor() before each encoder is created.
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
#if defined(__GNUC__)
#  pragma GCC visibility pop
#endif

#ifdef __cplusplus
}

/* Defined in libxul by gfx/skia/skia/src/ports/SkCpuEstimates_mozilla.cpp. */
const uint32_t* sk_cpu_estimates();

static inline void opus_mozilla_use_cpu_vendor() {
  opus_mozilla_set_cpu_estimates(sk_cpu_estimates());
}
#endif

#endif
