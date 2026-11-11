#!/usr/bin/env python3
"""Translate llvm-objdump output of libavutil/aarch64/tx_float_neon.o into C
that runs the same instructions, in the same order, on an emulated register
file. Only the instruction forms that file uses are accepted; anything else
is an error. FMLA/FMLS are fused (fmaf), as on ARM.

usage: a64toc.py tx.dis rodata.hex > tx_float_neonemu.c          (ffvpx)
       a64toc.py --celt tx.dis rodata.hex > celt_tx_neonemu.c   (libopus)

Inputs, from the object Firefox's aarch64 build assembles (on any aarch64
Linux host, or with an aarch64 cross toolchain):
  llvm-objdump -d -r --no-show-raw-insn tx_float_neon.o > tx.dis
  llvm-objcopy -O binary --only-section=.rodata tx_float_neon.o ro.bin
  xxd -p ro.bin > rodata.hex
For libopus, assemble celt/arm/celt_tx_neon.S with -DHAVE_CONFIG_H and an
empty config.h. Outputs:
  media/ffvpx/libavutil/x86/tx_float_neonemu.c
  media/libopus/celt/x86/celt_tx_neonemu.c
"""
import re, sys

CELT = sys.argv[1] == '--celt'
if CELT:
    del sys.argv[1]
dis = open(sys.argv[1]).read().split('\n')
rodata_hex = open(sys.argv[2]).read().split()

insns = []      # (addr, mnem, ops, reloc)
syms = {}       # addr -> name
words = {}      # addr -> u32 (literal pool)
cur = None
for line in dis:
    m = re.match(r'^([0-9a-f]{16}) <([^>]+)>:', line)
    if m:
        syms[int(m.group(1), 16)] = m.group(2)
        continue
    m = re.match(r'^\s+([0-9a-f]+):\s+(?:[0-9a-f]{2} [0-9a-f]{2} [0-9a-f]{2} [0-9a-f]{2}\s+)?\.word\s+0x([0-9a-f]+)', line)
    if m:
        words[int(m.group(1), 16)] = int(m.group(2), 16)
        continue
    m = re.match(r'^\s+([0-9a-f]+):\s+R_AARCH64_(\w+)\s+(\S+)', line)
    if m:
        a = int(m.group(1), 16)
        assert insns[-1][0] == a, line
        insns[-1] = insns[-1][:3] + ((m.group(2), m.group(3)),)
        continue
    m = re.match(r'^\s+([0-9a-f]+):\s+(\S+)\s*(.*)$', line)
    if m and not line.strip().startswith('Disassembly'):
        a = int(m.group(1), 16)
        ops = re.sub(r'\s*//.*$', '', m.group(3)).strip()
        insns.append((a, m.group(2), ops, None))

def split_ops(ops):
    # split on commas not inside [] or {}
    res, depth, cur = [], 0, ''
    for c in ops:
        if c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
        if c == ',' and depth == 0:
            res.append(cur.strip()); cur = ''
        else:
            cur += c
    if cur.strip():
        res.append(cur.strip())
    return res

entries = sorted(syms)
targets = set()
for a, mn, ops, r in insns:
    if mn in ('b', 'bl') or mn.startswith('b.'):
        targets.add(int(ops.split()[0], 16))
    elif mn in ('cbz', 'cbnz', 'tbz', 'tbnz'):
        targets.add(int(split_ops(ops)[-1].split()[0], 16))

out = []
emit = out.append
used = set()
retsites = []

def X(r):
    r = r.strip()
    if r in ('sp', 'wsp'):
        return 'R->x[31]', 64
    if r in ('xzr', 'wzr'):
        return '0', 64 if r[0] == 'x' else 32
    assert re.fullmatch(r'[xw]\d+', r), r
    return f'R->x[{r[1:]}]', 64 if r[0] == 'x' else 32

def setx(r, expr):
    reg, w = X(r)
    assert reg != '0'
    if w == 32:
        return f'{reg} = (uint32_t)({expr});'
    return f'{reg} = (uint64_t)({expr});'

def getx(r):
    reg, w = X(r)
    return reg if w == 64 else f'(uint32_t){reg}'

def imm(s):
    s = s.strip().lstrip('#')
    return int(s, 0)

def V(r):
    m = re.fullmatch(r'v(\d+)\.(\w+)', r.strip())
    assert m, r
    return int(m.group(1)), m.group(2)

def vlane(r):
    m = re.fullmatch(r'v(\d+)\.(\w)\[(\d)\]', r.strip())
    assert m, r
    return int(m.group(1)), m.group(2), int(m.group(3))

def split_ops(ops):
    # split on commas not inside [] or {}
    res, depth, cur = [], 0, ''
    for c in ops:
        if c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
        if c == ',' and depth == 0:
            res.append(cur.strip()); cur = ''
        else:
            cur += c
    if cur.strip():
        res.append(cur.strip())
    return res

def addr_mode(ops_rest):
    """ops_rest: list of remaining operands, e.g. ['[x0, #0x8]'] or
    ['[sp, #-0x60]!'] or ['[sp]', '#0x60'] or ['[x2, x10, lsl #3]']."""
    a = ops_rest[0]
    pre = a.endswith('!')
    a = a.rstrip('!')
    assert a[0] == '[' and a[-1] == ']', a
    parts = [p.strip() for p in a[1:-1].split(',')]
    base = X(parts[0])[0]
    if len(parts) == 1:
        off = '0'
    elif len(parts) == 2 and parts[1].startswith('#'):
        off = str(imm(parts[1]))
    else:
        r = X(parts[1])[0] if parts[1][0] == 'x' else f'(uint64_t)(uint32_t){X(parts[1])[0]}'
        sh = 0
        if len(parts) == 3:
            ext, _, amt = parts[2].partition(' ')
            assert ext == 'lsl' or (ext == 'uxtw' and parts[1][0] == 'w'), a
            sh = imm(amt) if amt else 0
        off = f'({r} << {sh})'
    post = None
    if len(ops_rest) > 1:
        assert not pre
        p = ops_rest[1]
        post = str(imm(p)) if p.startswith('#') else X(p)[0]
    return base, off, pre, post

def mem_seq(base, off, pre, post, body_fn, nbytes_total):
    """body_fn(addr_expr) -> code. Handles pre/post indexing."""
    if pre:
        return f'{base} += {off}; {{ uint8_t* A = (uint8_t*){base}; {body_fn("A")} }}'
    if post is not None:
        return f'{{ uint8_t* A = (uint8_t*){base}; {body_fn("A")} {base} += {post}; }}'
    return f'{{ uint8_t* A = (uint8_t*){base} + {off}; {body_fn("A")} }}'

def reglist(s):
    s = s.strip()
    assert s[0] == '{' and s[-1] == '}', s
    return [V(x) for x in s[1:-1].split(',')]

def tr(a, mn, ops, rel):
    o = split_ops(ops)
    if mn == 'nop':
        return ''
    if mn == 'ret':
        return 'RET();'
    if mn == 'b':
        return f'goto L_{int(o[0].split()[0],16):x};'
    if mn == 'bl':
        t = int(o[0].split()[0], 16)
        n = len(retsites); retsites.append(a + 4)
        return f'CALL(L_{t:x}, R_{a+4:x});'
    if mn == 'b.gt':
        return f'if (!F_Z && F_N == F_V) goto L_{int(o[0].split()[0],16):x};'
    if mn == 'b.eq':
        return f'if (F_Z) goto L_{int(o[0].split()[0],16):x};'
    cond = {'b.ne': '!F_Z', 'b.lt': 'F_N != F_V', 'b.ge': 'F_N == F_V',
            'b.le': '(F_Z || F_N != F_V)'}
    if mn in cond:
        return f'if ({cond[mn]}) goto L_{int(o[0].split()[0],16):x};'
    if mn in ('cbz', 'cbnz'):
        t = int(o[1].split()[0], 16)
        return f'if (({getx(o[0])} == 0) == {int(mn == "cbz")}) goto L_{t:x};'
    if mn in ('tbz', 'tbnz'):
        t = int(o[2].split()[0], 16)
        return f'if ((({getx(o[0])} >> {imm(o[1])}) & 1) == {int(mn == "tbnz")}) goto L_{t:x};'
    if mn == 'tst':
        w = X(o[0])[1]
        T = 'uint64_t' if w == 64 else 'uint32_t'
        S = 'int64_t' if w == 64 else 'int32_t'
        return (f'{{ {T} r_ = ({T}){getx(o[0])} & ({T}){imm(o[1])}ull; '
                f'F_N = ({S})r_ < 0; F_Z = r_ == 0; F_V = 0; }}')
    if mn == 'blr':
        n = len(retsites); retsites.append(a + 4)
        arms = ' else '.join(f'if (t_ == (uintptr_t)&{syms[e].replace("_neon", "_neonemu")}) CALL(L_{e:x}, R_{a+4:x});'
                             for e in entries)
        return f'{{ uint64_t t_ = {getx(o[0])}; {arms} else abort(); }}'
    if mn in ('lsl', 'lsr'):
        d, n_, sh = o
        op = '<<' if mn == 'lsl' else '>>'
        return setx(d, f'{getx(n_)} {op} {imm(sh)}')
    if mn == 'uxth':
        return setx(o[0], f'{getx(o[1])} & 0xffff')
    if mn in ('madd', 'msub'):
        d, n_, m_, a_ = o
        op = '+' if mn == 'madd' else '-'
        return setx(d, f'{getx(a_)} {op} {getx(n_)} * {getx(m_)}')
    if mn in ('cmp', 'subs'):
        if mn == 'cmp':
            d, n, m = None, o[0], o[1:]
        else:
            d, n, m = o[0], o[1], o[2:]
        w = X(n)[1]
        v = imm(m[0])
        if len(m) > 1:
            v <<= imm(m[1].replace('lsl', ''))
        T = 'uint64_t' if w == 64 else 'uint32_t'
        S = 'int64_t' if w == 64 else 'int32_t'
        code = (f'{{ {T} a_ = ({T}){getx(n)}, b_ = ({T}){v}ull, r_ = a_ - b_; '
                f'F_N = ({S})r_ < 0; F_Z = r_ == 0; '
                f'F_V = ((({S})a_ < 0) != (({S})b_ < 0)) && ((({S})r_ < 0) != (({S})a_ < 0)); ')
        if d:
            code += setx(d, 'r_') + ' '
        return code + '}'
    if mn in ('add', 'sub') and o[0][0] in 'xws':
        d, n, m = o[0], o[1], o[2]
        op = '+' if mn == 'add' else '-'
        if rel is not None:
            kind, sym = rel
            assert mn == 'add' and kind == 'ADD_ABS_LO12_NC', (a, rel)
            return setx(d, f'(uintptr_t){symexpr(sym)}')
        if m.startswith('#'):
            rhs = str(imm(m))
        else:
            rhs = getx(m)
            if len(o) > 3:
                assert o[3].startswith('lsl'), o
                rhs = f'((uint64_t){rhs} << {imm(o[3][3:])})'
        return setx(d, f'{getx(n)} {op} {rhs}')
    if mn == 'adrp':
        assert rel and rel[0] == 'ADR_PREL_PG_HI21', a
        return '/* adrp */'
    if mn == 'mov':
        d, s = o[0], o[1]
        if d[0] in 'xw' and s.startswith('#'):
            return setx(d, f'(int64_t){imm(s)}')
        if d[0] in 'xw' and (s[0] in 'xw' or s == 'sp'):
            return setx(d, getx(s))
        if d[0] in 'xw' and s.startswith('v'):
            n, t, l = vlane(s); assert t == 'd'
            return setx(d, f'R->v[{n}].d[{l}]')
        if d.startswith('v') and '[' in d:
            n, t, l = vlane(d)
            if s in ('xzr',):
                return f'R->v[{n}].d[{l}] = 0;'
            if s[0] == 'x':
                return f'R->v[{n}].d[{l}] = {getx(s)};'
            m_, t2, l2 = vlane(s)
            assert t == t2
            f = {'d': 'd', 's': 's'}[t]
            return f'{{ uint64_t t_ = R->v[{m_}].{f}[{l2}]; R->v[{n}].{f}[{l}] = t_; }}'
        n, t = V(d); m_, t2 = V(s)
        assert t == t2 == '16b'
        return f'R->v[{n}] = R->v[{m_}];'
    if mn in ('fadd', 'fsub', 'fmul', 'fmla', 'fmls', 'trn1', 'trn2', 'zip1', 'zip2', 'uzp1', 'uzp2'):
        d, td = V(o[0]); n, tn = V(o[1]); m_, tm = V(o[2])
        assert td == tn == tm, (a, ops)
        used.add(f'{mn}_{td}')
        return f'R->v[{d}] = {mn}_{td}(R->v[{d}], R->v[{n}], R->v[{m_}]);'
    if mn in ('rev64', 'fneg'):
        d, td = V(o[0]); n, tn = V(o[1]); assert td == tn
        used.add(f'{mn}_{td}')
        return f'R->v[{d}] = {mn}_{td}(R->v[{n}]);'
    if mn == 'ext':
        d, td = V(o[0]); n, _ = V(o[1]); m_, _ = V(o[2]); assert td == '16b'
        return f'R->v[{d}] = ext16(R->v[{n}], R->v[{m_}], {imm(o[3])});'
    if mn == 'dup':
        d, td = V(o[0]); n, t, l = vlane(o[1]); assert td == '2d' and t == 'd'
        return f'{{ uint64_t t_ = R->v[{n}].d[{l}]; R->v[{d}].d[0] = t_; R->v[{d}].d[1] = t_; }}'
    if mn in ('ldr', 'str', 'ldp', 'stp', 'ldrh'):
        regs = o[:2] if mn in ('ldp', 'stp') else o[:1]
        rest = o[len(regs):]
        if mn == 'ldr' and not rest[0].startswith('['):
            la = int(rest[0].split()[0], 16)
            r0 = regs[0]; assert r0[0] == 'w'
            return setx(r0, f'{words[la]}u')
        base, off, pre, post = addr_mode(rest)
        load = mn.startswith('ld')
        def body(A):
            code = ''
            pos = 0
            for r in regs:
                k = r[0]
                sz = {'x': 8, 'w': 4, 'd': 8, 'q': 16, 's': 4}[k]
                if mn in ('ldrh', 'strh'):
                    sz = 2
                idx = int(r[1:])
                if mn == 'ldrh':
                    code += f'{{ uint16_t t_; memcpy(&t_, {A}+{pos}, 2); R->x[{idx}] = t_; }} '
                elif load and k == 's':
                    code += f'memset(&R->v[{idx}], 0, 16); memcpy(&R->v[{idx}].s[0], {A}+{pos}, 4); '
                elif not load and k == 's':
                    code += f'memcpy({A}+{pos}, &R->v[{idx}].s[0], 4); '
                elif load:
                    if k == 'x':
                        code += f'memcpy(&R->x[{idx}], {A}+{pos}, 8); '
                    elif k == 'w':
                        code += f'{{ uint32_t t_; memcpy(&t_, {A}+{pos}, 4); R->x[{idx}] = t_; }} '
                    elif k == 'd':
                        code += f'memcpy(&R->v[{idx}].d[0], {A}+{pos}, 8); R->v[{idx}].d[1] = 0; '
                    elif k == 'q':
                        code += f'memcpy(&R->v[{idx}], {A}+{pos}, 16); '
                else:
                    if k == 'x':
                        code += f'memcpy({A}+{pos}, &R->x[{idx}], 8); '
                    elif k == 'w':
                        code += f'{{ uint32_t t_ = (uint32_t)R->x[{idx}]; memcpy({A}+{pos}, &t_, 4); }} '
                    elif k == 'd':
                        code += f'memcpy({A}+{pos}, &R->v[{idx}].d[0], 8); '
                    elif k == 'q':
                        code += f'memcpy({A}+{pos}, &R->v[{idx}], 16); '
                pos += sz
            return code
        return mem_seq(base, off, pre, post, body, None)
    if mn in ('ld1', 'st1', 'ld2r', 'ld1r', 'ld2'):
        lst = o[0]
        rest = o[1:]
        base, off, pre, post = addr_mode(rest)
        m = re.fullmatch(r'\{\s*v(\d+)\.([ds])\s*\}\[(\d)\]', lst.replace(' ', ''))
        if m:
            n, t, l = int(m.group(1)), m.group(2), int(m.group(3))
            sz = 8 if t == 'd' else 4
            assert post is None
            if mn == 'ld1':
                return mem_seq(base, off, pre, post, lambda A: f'memcpy(&R->v[{n}].{t}[{l}], {A}, {sz});', None)
            assert mn == 'st1'
            return mem_seq(base, off, pre, post, lambda A: f'memcpy({A}, &R->v[{n}].{t}[{l}], {sz});', None)
        regs = reglist(lst)
        if mn == 'ld1r':
            assert [t for _, t in regs] == ['2d']
            r0 = regs[0][0]
            return mem_seq(base, off, pre, post, lambda A:
                f'{{ uint64_t a_; memcpy(&a_, {A}, 8); R->v[{r0}].d[0] = R->v[{r0}].d[1] = a_; }}', None)
        if mn == 'ld2':
            assert [t for _, t in regs] == ['2s', '2s']
            (r0, _), (r1, _) = regs
            return mem_seq(base, off, pre, post, lambda A:
                f'{{ uint32_t e_[4]; memcpy(e_, {A}, 16); memset(&R->v[{r0}], 0, 16); memset(&R->v[{r1}], 0, 16); '
                f'R->v[{r0}].s[0] = e_[0]; R->v[{r1}].s[0] = e_[1]; R->v[{r0}].s[1] = e_[2]; R->v[{r1}].s[1] = e_[3]; }}', None)
        if mn == 'ld2r':
            assert [t for _, t in regs] == ['2d', '2d']
            (r0, _), (r1, _) = regs
            return mem_seq(base, off, pre, post, lambda A:
                f'{{ uint64_t a_, b_; memcpy(&a_, {A}, 8); memcpy(&b_, {A}+8, 8); '
                f'R->v[{r0}].d[0] = R->v[{r0}].d[1] = a_; R->v[{r1}].d[0] = R->v[{r1}].d[1] = b_; }}', None)
        assert all(t == '4s' for _, t in regs), ops
        def body(A):
            code = ''
            for i, (n, _) in enumerate(regs):
                if mn == 'ld1':
                    code += f'memcpy(&R->v[{n}], {A}+{16*i}, 16); '
                else:
                    code += f'memcpy({A}+{16*i}, &R->v[{n}], 16); '
            return code
        return mem_seq(base, off, pre, post, body, None)
    raise SystemExit(f'unhandled {a:x}: {mn} {ops}')

ROSYM = {'.rodata': 'kRodata'}
def symexpr(sym):
    m = re.fullmatch(r'\.rodata(?:\+0x([0-9a-f]+))?', sym)
    if m:
        return f'((const uint8_t*)kRodata + {int(m.group(1) or "0", 16)})'
    assert sym.startswith('ff_tx_tab_') or sym.startswith('celt_tx_tab_'), sym
    return f'(const void*){sym}'

body = []
for a, mn, ops, rel in insns:
    lab = ''
    if a in targets or a in syms:
        lab = f'L_{a:x}: '
    code = tr(a, mn, ops, rel)
    if a in syms:
        body.append(f'  /* {syms[a]} */')
    body.append(f'  {lab}{code}  /* {a:x}: {mn} {ops} */' if lab or code else f'  /* {a:x}: {mn} */')
    if mn in ('bl', 'blr'):
        body.append(f'  R_{a+4:x}:;')

tabs = sorted({r[1] for _, _, _, r in insns if r and r[1].startswith(('ff_tx_tab_', 'celt_tx_tab_'))})
rod = bytes.fromhex(''.join(rodata_hex))

CELT_HEAD = '''/* Generated by a64toc.py --celt from celt/arm/celt_tx_neon.S (libopus; the
 * FFT/MDCT code is derived from FFmpeg's libavutil/aarch64/tx_float_neon.S,
 * Copyright (c) Lynne). Do not edit: regenerate.
 *
 * general.cpu_identity = ARM64 on x86-64: the AArch64 NEON inverse MDCT,
 * executed instruction for instruction on an emulated AArch64 register file,
 * so the CELT decoder returns the samples an ARM CPU's would. FMLA/FMLS are
 * fused (fmaf), every other float operation is one IEEE single-precision
 * rounding, as on ARM. NaN payload and sign propagation follow x86, not ARM.
 */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "celt_tx_tables.h"
#include "x86/celt_neonemu.h"

#if defined(OPUS_X86_NEONEMU)

typedef union {
    float f[4];
    uint32_t s[4];
    uint64_t d[2];
    uint8_t b[16];
} NV;

typedef struct {
    uint64_t x[32]; /* x[31] is sp */
    NV v[32];
} NRegs;
'''
if CELT:
    print(CELT_HEAD)
else:
  print('''/* Generated by a64toc.py from libavutil/aarch64/tx_float_neon.S (FFmpeg,
 * LGPL 2.1 or later, Copyright (c) Lynne). Do not edit: regenerate.
 *
 * general.cpu_identity = ARM64 on x86-64: the NEON FFT codelets, executed
 * instruction for instruction on an emulated AArch64 register file, so a
 * transform returns the bits an ARM CPU's would. FMLA/FMLS are fused (fmaf),
 * every other float operation is one IEEE single-precision rounding, as on
 * ARM. NaN payload and sign propagation follow x86, not ARM.
 */

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#ifdef NEONEMU_STANDALONE
typedef struct AVTXContext AVTXContext;
#else
#define TX_FLOAT
#include "libavutil/tx_priv.h"
#include "libavutil/attributes.h"
#endif

typedef union {
    float f[4];
    uint32_t s[4];
    uint64_t d[2];
    uint8_t b[16];
} NV;

typedef struct {
    uint64_t x[32]; /* x[31] is sp */
    NV v[32];
} NRegs;
''')
for t in tabs:
    if not CELT:
        print(f'extern const float {t}[];')
print('static const uint8_t kRodata[%d] __attribute__((aligned(16))) = {%s};' % (len(rod), ', '.join(str(b) for b in rod)))
EXTRA2 = {
    'fmul_2s': 'static inline NV fmul_2s(NV d, NV n, NV m) LANES2(n.f[i] * m.f[i])',
    'fmla_2s': 'static inline NV fmla_2s(NV d, NV n, NV m) LANES2(fmaf(n.f[i], m.f[i], d.f[i]))',
    'fmls_2s': 'static inline NV fmls_2s(NV d, NV n, NV m) LANES2(fmaf(-n.f[i], m.f[i], d.f[i]))',
    'rev64_2s': 'static inline NV rev64_2s(NV n) { NV r_; r_.s[0] = n.s[1]; r_.s[1] = n.s[0]; r_.d[1] = 0; return r_; }',
    'zip1_2s': 'static inline NV zip1_2s(NV d, NV n, NV m) { NV r_; r_.s[0] = n.s[0]; r_.s[1] = m.s[0]; r_.d[1] = 0; return r_; }',
    'zip2_2s': 'static inline NV zip2_2s(NV d, NV n, NV m) { NV r_; r_.s[0] = n.s[1]; r_.s[1] = m.s[1]; r_.d[1] = 0; return r_; }',
    'zip1_4s': 'static inline NV zip1_4s(NV d, NV n, NV m) { NV r_; r_.s[0] = n.s[0]; r_.s[1] = m.s[0]; r_.s[2] = n.s[1]; r_.s[3] = m.s[1]; return r_; }',
    'zip2_4s': 'static inline NV zip2_4s(NV d, NV n, NV m) { NV r_; r_.s[0] = n.s[2]; r_.s[1] = m.s[2]; r_.s[2] = n.s[3]; r_.s[3] = m.s[3]; return r_; }',
}
EXTRA = ''
if CELT:
    EXTRA = '#define LANES2(expr) { NV r_; for (int i = 0; i < 2; i++) r_.f[i] = (expr); r_.d[1] = 0; return r_; }\n'
    EXTRA += '\n'.join(v for k, v in EXTRA2.items() if k in used) + '\n'
    for a in entries:
        EXTRA += f'void {syms[a].replace("_neon", "_neonemu")}(const OpusTXContext* s, void* out, void* in, ptrdiff_t stride);\n'
    EXTRA = '\n' + EXTRA
print(r'''
#define LANES4(expr) { NV r_; for (int i = 0; i < 4; i++) r_.f[i] = (expr); return r_; }
static inline NV fadd_4s(NV d, NV n, NV m) LANES4(n.f[i] + m.f[i])
static inline NV fsub_4s(NV d, NV n, NV m) LANES4(n.f[i] - m.f[i])
static inline NV fmul_4s(NV d, NV n, NV m) LANES4(n.f[i] * m.f[i])
static inline NV fmla_4s(NV d, NV n, NV m) LANES4(fmaf(n.f[i], m.f[i], d.f[i]))
static inline NV fmls_4s(NV d, NV n, NV m) LANES4(fmaf(-n.f[i], m.f[i], d.f[i]))
static inline NV fneg_4s(NV n) LANES4(-n.f[i])
static inline NV fneg_2s(NV n) { NV r_; r_.f[0] = -n.f[0]; r_.f[1] = -n.f[1]; r_.d[1] = 0; return r_; }
static inline NV rev64_4s(NV n) { NV r_; r_.s[0] = n.s[1]; r_.s[1] = n.s[0]; r_.s[2] = n.s[3]; r_.s[3] = n.s[2]; return r_; }
static inline NV trn1_4s(NV d, NV n, NV m) { NV r_; r_.s[0] = n.s[0]; r_.s[1] = m.s[0]; r_.s[2] = n.s[2]; r_.s[3] = m.s[2]; return r_; }
static inline NV trn2_4s(NV d, NV n, NV m) { NV r_; r_.s[0] = n.s[1]; r_.s[1] = m.s[1]; r_.s[2] = n.s[3]; r_.s[3] = m.s[3]; return r_; }
static inline NV zip1_2d(NV d, NV n, NV m) { NV r_; r_.d[0] = n.d[0]; r_.d[1] = m.d[0]; return r_; }
static inline NV zip2_2d(NV d, NV n, NV m) { NV r_; r_.d[0] = n.d[1]; r_.d[1] = m.d[1]; return r_; }
static inline NV uzp1_2d(NV d, NV n, NV m) { NV r_; r_.d[0] = n.d[0]; r_.d[1] = m.d[0]; return r_; }
static inline NV uzp2_2d(NV d, NV n, NV m) { NV r_; r_.d[0] = n.d[1]; r_.d[1] = m.d[1]; return r_; }
static inline NV ext16(NV n, NV m, int k) { NV r_; for (int i = 0; i < 16; i++) r_.b[i] = i + k < 16 ? n.b[i + k] : m.b[i + k - 16]; return r_; }
''' + EXTRA + r'''
#define CALL(target, site) do { RS[rsp++] = &&site; goto target; } while (0)
#define RET() do { if (rsp == 0) return; goto *RS[--rsp]; } while (0)

static void neonemu_run(int entry, NRegs* R) {
    void* RS[64];
    int rsp = 0;
    int F_N = 0, F_Z = 0, F_V = 0;
    (void)F_N; (void)F_V;
    switch (entry) {''')
for i, a in enumerate(entries):
    print(f'      case {i}: goto L_{a:x};')
print('      default: return;\n    }')
print('\n'.join(body))
print('}\n')
if CELT:
    print('''static void neonemu_call(int entry, const void* s, void* out, void* in,
                         ptrdiff_t stride) {
    NRegs R;
    uint64_t stack[512] __attribute__((aligned(16)));
    memset(&R, 0, sizeof(R));
    R.x[0] = (uintptr_t)s;
    R.x[1] = (uintptr_t)out;
    R.x[2] = (uintptr_t)in;
    R.x[3] = (uint64_t)stride;
    R.x[31] = (uintptr_t)(stack + 512);
    neonemu_run(entry, &R);
}
''')
    for i, a in enumerate(entries):
        name = syms[a].replace('_neon', '_neonemu')
        print(f'void {name}(const OpusTXContext* s, void* out, void* in, ptrdiff_t stride) {{ neonemu_call({i}, s, out, in, stride); }}')
    print('\n#endif /* OPUS_X86_NEONEMU */')
    sys.exit(0)
print('''static void neonemu_call(int entry, AVTXContext* s, void* out, void* in,
                         ptrdiff_t stride) {
    NRegs R;
    uint64_t stack[64] __attribute__((aligned(16)));
    memset(&R, 0, sizeof(R));
    R.x[0] = (uintptr_t)s;
    R.x[1] = (uintptr_t)out;
    R.x[2] = (uintptr_t)in;
    R.x[3] = (uint64_t)stride;
    R.x[31] = (uintptr_t)(stack + 64);
    neonemu_run(entry, &R);
}
''')
for i, a in enumerate(entries):
    name = syms[a].replace('_neon', '_neonemu')
    print(f'void {name}(AVTXContext* s, void* out, void* in, ptrdiff_t stride) {{ neonemu_call({i}, s, out, in, stride); }}')

print(r"""
#ifndef NEONEMU_STANDALONE
/* The codelet list of aarch64/tx_float_init.c, with the emulated functions
 * and no CPU requirement. tx.c uses it instead of the x86 list while
 * av_tx_cfp_emulate_arm64(1) is in effect. */
static av_cold int neonemu_init(AVTXContext *s, const FFTXCodelet *cd,
                                uint64_t flags, FFTXCodeletOptions *opts,
                                int len, int inv, const void *scale)
{
    ff_tx_init_tabs_float(len);
    if (cd->max_len == 2)
        return ff_tx_gen_ptwo_revtab(s, opts);
    else
        return ff_tx_gen_split_radix_parity_revtab(s, len, inv, opts, 8, 0);
}

#define AV_CPU_FLAG_NEONEMU 0 /* runs on any CPU */
#define NONE NULL

const FFTXCodelet * const ff_tx_codelet_list_float_neonemu[] = {
    TX_DEF(fft2,      FFT,  2,  2, 2, 0, 128, NONE,         neonemu, NEONEMU, AV_TX_INPLACE, 0),
    TX_DEF(fft2,      FFT,  2,  2, 2, 0, 192, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_PRESHUFFLE, 0),
    TX_DEF(fft4_fwd,  FFT,  4,  4, 2, 0, 128, NONE,         neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_FORWARD_ONLY, 0),
    TX_DEF(fft4_fwd,  FFT,  4,  4, 2, 0, 192, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_PRESHUFFLE, 0),
    TX_DEF(fft4_inv,  FFT,  4,  4, 2, 0, 128, NONE,         neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_INVERSE_ONLY, 0),
    TX_DEF(fft8,      FFT,  8,  8, 2, 0, 128, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE, 0),
    TX_DEF(fft8_ns,   FFT,  8,  8, 2, 0, 192, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_PRESHUFFLE, 0),
    TX_DEF(fft16,     FFT, 16, 16, 2, 0, 128, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE, 0),
    TX_DEF(fft16_ns,  FFT, 16, 16, 2, 0, 192, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_PRESHUFFLE, 0),
    TX_DEF(fft32,     FFT, 32, 32, 2, 0, 128, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE, 0),
    TX_DEF(fft32_ns,  FFT, 32, 32, 2, 0, 192, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_PRESHUFFLE, 0),
    TX_DEF(fft_sr,    FFT, 64, 131072, 2, 0, 128, neonemu_init, neonemu, NEONEMU, 0, 0),
    TX_DEF(fft_sr_ns, FFT, 64, 131072, 2, 0, 192, neonemu_init, neonemu, NEONEMU, AV_TX_INPLACE | FF_TX_PRESHUFFLE, 0),
    NULL,
};
#endif
""")
