/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Firefox aarch64's inverse MDCT (arm/celt_mdct_tx.c) on x86, for arch
 * OPUS_ARCH_X86_NEONEMU: the same driver and context tables, with the NEON
 * kernels replaced by their translation in celt_tx_neonemu.c. */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "x86/celt_neonemu.h"

#if defined(OPUS_X86_NEONEMU)

#define OPUS_ARM_TX_MDCT (1)
#define celt_tx_fft4_fwd_float_neon        celt_tx_fft4_fwd_float_neonemu
#define celt_tx_fft8_ns_float_neon         celt_tx_fft8_ns_float_neonemu
#define celt_tx_fft16_ns_float_neon        celt_tx_fft16_ns_float_neonemu
#define celt_tx_fft32_ns_float_neon        celt_tx_fft32_ns_float_neonemu
#define celt_tx_fft_sr_ns_float_neon       celt_tx_fft_sr_ns_float_neonemu
#define celt_tx_fft_pfa_15xM_ns_float_neon celt_tx_fft_pfa_15xM_ns_float_neonemu
#define celt_tx_mdct_inv_float_neon        celt_tx_mdct_inv_float_neonemu
#define celt_tx_mdct_kernel                celt_tx_mdct_kernel_neonemu
#define clt_mdct_backward_tx               clt_mdct_backward_neonemu

#include "arm/celt_mdct_tx.c"

#endif
