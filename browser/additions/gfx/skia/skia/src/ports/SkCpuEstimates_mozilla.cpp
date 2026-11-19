/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Which recorded RCPPS/RSQRTPS table Skia's raster pipeline uses
// (src/opts/SkCpuEstimates.h) and libopus's PVQ search
// (media/libopus/include/opus_cpu_estimates.h) use, from
// general.cpu_identity (1 Intel, 2 AMD). On aarch64 an x86 identity always
// needs its table, since the emulated SSE code has no RCPPS of its own.

#include "include/core/SkTypes.h"

#if defined(SK_CPU_X86)

#  include "mozilla/StaticPrefs_general.h"
#  include "src/opts/SkCpuEstimateTables.h"

#  include <string.h>
#  if defined(_MSC_VER)
#    include <intrin.h>
#  else
#    include <cpuid.h>
#  endif

static uint32_t HostVendor() {
  unsigned regs[4] = {0, 0, 0, 0};  // eax, ebx, ecx, edx
#  if defined(_MSC_VER)
  __cpuid(reinterpret_cast<int*>(regs), 0);
#  else
  __get_cpuid(0, &regs[0], &regs[1], &regs[2], &regs[3]);
#  endif
  char id[13] = {};
  memcpy(id, &regs[1], 4);
  memcpy(id + 4, &regs[3], 4);
  memcpy(id + 8, &regs[2], 4);
  if (!strcmp(id, "GenuineIntel")) {
    return SK_CPU_VENDOR_INTEL;
  }
  if (!strcmp(id, "AuthenticAMD")) {
    return SK_CPU_VENDOR_AMD;
  }
  return SK_CPU_VENDOR_HOST;
}

const uint32_t* sk_cpu_estimates() {
  static const uint32_t sHost = HostVendor();
  const uint32_t vendor = mozilla::StaticPrefs::general_cpu_identity();
  if ((vendor != SK_CPU_VENDOR_INTEL && vendor != SK_CPU_VENDOR_AMD) ||
      vendor == sHost) {
    return nullptr;
  }
  return kSkCpuEstimateTables[vendor - 1];
}

bool sk_cpu_emulates_arm64() {
  return mozilla::StaticPrefs::general_cpu_identity() == SK_CPU_IDENTITY_ARM64;
}

bool sk_cpu_emulates_x86() { return false; }

#elif defined(SK_CPU_ARM64)

#  include "mozilla/StaticPrefs_general.h"
#  include "src/opts/SkCpuEstimateTables.h"

static bool IsX86Vendor(uint32_t vendor) {
  return vendor == SK_CPU_VENDOR_INTEL || vendor == SK_CPU_VENDOR_AMD;
}

// An x86 identity here is always emulated, so its vendor's table always applies.
const uint32_t* sk_cpu_estimates() {
  const uint32_t vendor = mozilla::StaticPrefs::general_cpu_identity();
  return IsX86Vendor(vendor) ? kSkCpuEstimateTables[vendor - 1] : nullptr;
}

bool sk_cpu_emulates_arm64() { return false; }

bool sk_cpu_emulates_x86() {
  return IsX86Vendor(mozilla::StaticPrefs::general_cpu_identity());
}

#else

const uint32_t* sk_cpu_estimates() { return nullptr; }

bool sk_cpu_emulates_arm64() { return false; }

bool sk_cpu_emulates_x86() { return false; }

#endif

// Every architecture's sk_cpu_estimates() above, resolved for the pipeline.
const uint32_t* gSkCpuEstimatesForPipeline = nullptr;

void sk_cpu_estimates_init_pipeline() { gSkCpuEstimatesForPipeline = sk_cpu_estimates(); }
