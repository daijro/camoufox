/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*-
 * vim: set ts=8 sts=2 et sw=2 tw=80:
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/*
 * sin, cos, tan and pow exactly as the Windows Universal CRT computes them
 * (ucrtbase.dll, x64, FMA3 code path), for builds that present as Windows on
 * another OS. Math.sin/cos/tan/pow are a cheap, well-known fingerprint: the
 * last bit of their results differs between the platform math libraries, so a
 * page can tell glibc or fdlibm apart from the CRT. These are ports of the
 * CRT's own algorithms, checked bit for bit against ucrtbase.dll by
 * browser/tests/ucrt-math/check.py and against Windows Firefox by the
 * windows-crt-math patch guard.
 *
 * Only built where JS_UCRT_MATH is defined (js/src/builtin/moz.build): not on
 * Windows, which already calls the CRT, and only on 64-bit targets (the
 * argument reduction uses a 64x64->128-bit multiply).
 */

#ifndef builtin_UcrtMath_h
#define builtin_UcrtMath_h

#ifdef __cplusplus
extern "C" {
#endif

double ucrt_sin(double x);
double ucrt_cos(double x);
double ucrt_tan(double x);
double ucrt_pow(double x, double y);

#ifdef __cplusplus
}
#endif

#endif /* builtin_UcrtMath_h */
