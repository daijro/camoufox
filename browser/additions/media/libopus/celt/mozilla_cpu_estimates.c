/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The table and the arm64 and x86 switches opus_cpu_estimates.h describes.
 * Built on every CPU so that Gecko links the same way everywhere; x86 reads
 * the table and the arm64 switch, aarch64 the table and the x86 switch (the
 * PVQ search and opus_select_arch). */

#include <stdatomic.h>

#include "opus_cpu_estimates.h"
#include "cpu_support.h"

static _Atomic(const uint32_t*) sTable;

void opus_mozilla_set_cpu_estimates(const uint32_t* table) {
  atomic_store_explicit(&sTable, table, memory_order_relaxed);
}

const uint32_t* opus_mozilla_cpu_estimates(void) {
  return atomic_load_explicit(&sTable, memory_order_relaxed);
}

static _Atomic(int) sEmulateArm64;

void opus_mozilla_set_emulate_arm64(int on) {
  atomic_store_explicit(&sEmulateArm64, on != 0, memory_order_relaxed);
}

int opus_mozilla_emulates_arm64(void) {
  return atomic_load_explicit(&sEmulateArm64, memory_order_relaxed);
}

static _Atomic(int) sEmulateX86;

void opus_mozilla_set_emulate_x86(int on) {
  atomic_store_explicit(&sEmulateX86, on != 0, memory_order_relaxed);
}

int opus_mozilla_emulates_x86(void) {
  return atomic_load_explicit(&sEmulateX86, memory_order_relaxed);
}

#if defined(OPUS_ARM_X86EMU)
int opus_select_arch(void) {
  return opus_mozilla_emulates_x86() ? OPUS_ARCH_ARM_X86EMU : 0;
}
#endif
