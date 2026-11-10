/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The table opus_cpu_estimates.h describes. Built on every CPU so that Gecko
 * links the same way everywhere; only x86's PVQ search reads it. */

#include <stdatomic.h>

#include "opus_cpu_estimates.h"

static _Atomic(const uint32_t*) sTable;

void opus_mozilla_set_cpu_estimates(const uint32_t* table) {
  atomic_store_explicit(&sTable, table, memory_order_relaxed);
}

const uint32_t* opus_mozilla_cpu_estimates(void) {
  return atomic_load_explicit(&sTable, memory_order_relaxed);
}
