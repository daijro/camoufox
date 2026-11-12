/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Switches the rest of an x86-64 translation unit to Skia's AArch64 code,
// built against SkNeonEmu.h, in namespace neonemu. The _neonemu.cpp files
// include every header the opts code needs first, under the host's own
// settings, then this, then the opts code. Each such file is the whole of
// its translation unit, so nothing has to be switched back.

#include "include/private/base/SkFeatures.h"

#if !defined(SK_CPU_X86)
    #error The ARM64 tier is built on x86-64 only
#endif

#undef SK_CPU_X64_LEVEL
#define SK_CPU_X64_LEVEL 0
#define SK_ARM_HAS_NEON 1
#define SK_CPU_ARM64 1
#define SK_NEON_EMU 1
#define SK_OPTS_NS neonemu
#define DEFINE_DEFAULT(name)  // only the default tier defines the pointers
