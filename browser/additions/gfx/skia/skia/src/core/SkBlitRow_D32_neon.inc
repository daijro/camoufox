/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// SkBlitRow_D32.cpp's NEON blit_row_s32_blend and blit_row_s32a_blend,
// moved here unchanged so SkBlitRow_opts_neonemu.cpp can build them against
// SkNeonEmu.h as well. The includer provides the NEON intrinsics.

    static void blit_row_s32_blend(SkPMColor* dst, const SkPMColor* src, int count, U8CPU alpha) {
        SkASSERT(alpha <= 255);

        uint16_t src_scale = SkAlpha255To256(alpha);
        uint16_t dst_scale = 256 - src_scale;

        while (count >= 2) {
            uint8x8_t vsrc, vdst, vres;
            uint16x8_t vsrc_wide, vdst_wide;

            vsrc = vreinterpret_u8_u32(vld1_u32(src));
            vdst = vreinterpret_u8_u32(vld1_u32(dst));

            vsrc_wide = vmovl_u8(vsrc);
            vsrc_wide = vmulq_u16(vsrc_wide, vdupq_n_u16(src_scale));

            vdst_wide = vmull_u8(vdst, vdup_n_u8(dst_scale));

            vdst_wide += vsrc_wide;
            vres = vshrn_n_u16(vdst_wide, 8);

            vst1_u32(dst, vreinterpret_u32_u8(vres));

            src += 2;
            dst += 2;
            count -= 2;
        }

        if (count == 1) {
            uint8x8_t vsrc = vdup_n_u8(0), vdst = vdup_n_u8(0), vres;
            uint16x8_t vsrc_wide, vdst_wide;

            vsrc = vreinterpret_u8_u32(vld1_lane_u32(src, vreinterpret_u32_u8(vsrc), 0));
            vdst = vreinterpret_u8_u32(vld1_lane_u32(dst, vreinterpret_u32_u8(vdst), 0));

            vsrc_wide = vmovl_u8(vsrc);
            vsrc_wide = vmulq_u16(vsrc_wide, vdupq_n_u16(src_scale));
            vdst_wide = vmull_u8(vdst, vdup_n_u8(dst_scale));
            vdst_wide += vsrc_wide;
            vres = vshrn_n_u16(vdst_wide, 8);

            vst1_lane_u32(dst, vreinterpret_u32_u8(vres), 0);
        }
    }

    static void blit_row_s32a_blend(SkPMColor* dst, const SkPMColor* src, int count, U8CPU alpha) {
        SkASSERT(alpha < 255);

        unsigned alpha256 = SkAlpha255To256(alpha);

        if (count & 1) {
            uint8x8_t vsrc = vdup_n_u8(0), vdst = vdup_n_u8(0), vres;
            uint16x8_t vdst_wide, vsrc_wide;
            unsigned dst_scale;

            vsrc = vreinterpret_u8_u32(vld1_lane_u32(src, vreinterpret_u32_u8(vsrc), 0));
            vdst = vreinterpret_u8_u32(vld1_lane_u32(dst, vreinterpret_u32_u8(vdst), 0));

            dst_scale = vget_lane_u8(vsrc, 3);
            dst_scale = SkAlphaMulInv256(dst_scale, alpha256);

            vsrc_wide = vmovl_u8(vsrc);
            vsrc_wide = vmulq_n_u16(vsrc_wide, alpha256);

            vdst_wide = vmovl_u8(vdst);
            vdst_wide = vmulq_n_u16(vdst_wide, dst_scale);

            vdst_wide += vsrc_wide;
            vres = vshrn_n_u16(vdst_wide, 8);

            vst1_lane_u32(dst, vreinterpret_u32_u8(vres), 0);
            dst++;
            src++;
            count--;
        }

        uint8x8_t alpha_mask;
        static const uint8_t alpha_mask_setup[] = {3,3,3,3,7,7,7,7};
        alpha_mask = vld1_u8(alpha_mask_setup);

        while (count) {

            uint8x8_t vsrc, vdst, vres, vsrc_alphas;
            uint16x8_t vdst_wide, vsrc_wide, vsrc_scale, vdst_scale;

            __builtin_prefetch(src+32);
            __builtin_prefetch(dst+32);

            vsrc = vreinterpret_u8_u32(vld1_u32(src));
            vdst = vreinterpret_u8_u32(vld1_u32(dst));

            vsrc_scale = vdupq_n_u16(alpha256);

            vsrc_alphas = vtbl1_u8(vsrc, alpha_mask);
            vdst_scale = vmovl_u8(vsrc_alphas);
            // Calculate SkAlphaMulInv256(vdst_scale, vsrc_scale).
            // A 16-bit lane would overflow if we used 0xFFFF here,
            // so use an approximation with 0xFF00 that is off by 1,
            // and add back 1 after to get the correct value.
            // This is valid if alpha256 <= 255.
            vdst_scale = vmlsq_u16(vdupq_n_u16(0xFF00), vdst_scale, vsrc_scale);
            vdst_scale = vsraq_n_u16(vdst_scale, vdst_scale, 8);
            vdst_scale = vsraq_n_u16(vdupq_n_u16(1), vdst_scale, 8);

            vsrc_wide = vmovl_u8(vsrc);
            vsrc_wide *= vsrc_scale;

            vdst_wide = vmovl_u8(vdst);
            vdst_wide *= vdst_scale;

            vdst_wide += vsrc_wide;
            vres = vshrn_n_u16(vdst_wide, 8);

            vst1_u32(dst, vreinterpret_u32_u8(vres));

            src += 2;
            dst += 2;
            count -= 2;
        }
    }

