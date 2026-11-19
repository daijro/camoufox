/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Skia's AArch64 A8 mask blitter on x86-64, for general.cpu_identity = ARM64.

#include "include/private/base/SkFeatures.h"

#if defined(SK_CPU_X86) && !defined(SK_ENABLE_OPTIMIZE_SIZE)

#include "include/core/SkTypes.h"
#include "include/private/base/SkFeatures.h"
#include "include/private/base/SkMalloc.h"
#include "include/private/base/SkSpan_impl.h"
#include "include/private/base/SkTemplates.h"
#include "modules/skcms/skcms.h"
#include "src/base/SkMSAN.h"
#include "src/base/SkUtils.h"
#include "src/base/SkVx.h"
#include "src/core/Sk4px.h"
#include "src/core/SkBitmapProcState.h"
#include "src/core/SkBlitMask.h"
#include "src/core/SkBlitRow.h"
#include "src/core/SkColorData.h"
#include "src/core/SkOpts.h"
#include "src/core/SkRasterPipeline.h"
#include "src/core/SkRasterPipelineContextUtils.h"
#include "src/core/SkSwizzlePriv.h"
#include "src/shaders/SkPerlinNoiseShaderType.h"
#include "src/sksl/tracing/SkSLTraceHook.h"

#include "src/opts/SkOpts_NeonEmuTarget.h"

#include "src/opts/SkBlitMask_opts.h"

namespace SkOpts {
    void Init_BlitMask_neonemu() {
        blit_mask_d32_a8 = neonemu::blit_mask_d32_a8;
    }
}  // namespace SkOpts

#endif  // SK_CPU_X86 && !SK_ENABLE_OPTIMIZE_SIZE
