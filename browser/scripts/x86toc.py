#!/usr/bin/env python3
"""Translate llvm-objdump output of libavutil/x86/tx_float.o into C that runs
the same instructions, in the same order, on an emulated x86-64 register
file. Only the instruction forms that file uses are accepted; anything else
is an error. The FMA3 forms are fused (fmaf), as on x86. a64toc.py is the
reverse direction.

usage: x86toc.py tx.dis rodata.hex > tx_float_x86emu.c

Inputs, from the object Firefox's x86-64 Linux build assembles:
  llvm-objdump -d -r --no-show-raw-insn -M intel tx_float.o > tx.dis
  llvm-objcopy -O binary --only-section=.rodata tx_float.o ro.bin
  xxd -p ro.bin > rodata.hex
Output: media/ffvpx/libavutil/aarch64/tx_float_x86emu.c
"""
import re, sys

dis = open(sys.argv[1]).read().split('\n')
rod = bytes.fromhex(''.join(open(sys.argv[2]).read().split()))

insns = []      # [addr, mnem, ops, reloc]
syms = {}       # addr -> name
for line in dis:
    m = re.match(r'^([0-9a-f]{16}) <([^>]+)>:', line)
    if m:
        syms[int(m.group(1), 16)] = m.group(2)
        continue
    m = re.match(r'^\s+([0-9a-f]+):\s+R_X86_64_(\w+)\s+(\S+)', line)
    if m:
        assert m.group(2) == 'PC32', line
        insns[-1][3] = (int(m.group(1), 16), m.group(3))
        continue
    m = re.match(r'^\s+([0-9a-f]+):\s+(\S+)\s*(.*)$', line)
    if m and not line.startswith('Disassembly'):
        ops = re.sub(r'\s*#.*$', '', m.group(3)).strip()
        insns.append([int(m.group(1), 16), m.group(2), ops, None])

nexta = {insns[i][0]: insns[i + 1][0] for i in range(len(insns) - 1)}
entries = sorted(a for a, n in syms.items() if '.' not in n)

GPR = ['rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi'] + [f'r{i}' for i in range(8, 16)]
GPR32 = ['eax', 'ecx', 'edx', 'ebx', 'esp', 'ebp', 'esi', 'edi'] + [f'r{i}d' for i in range(8, 16)]

def gpr(r):
    """-> (C lvalue, width)"""
    if r in GPR:
        return f'R->r[{GPR.index(r)}]', 64
    assert r in GPR32, r
    return f'R->r[{GPR32.index(r)}]', 32

def setg(r, expr):
    reg, w = gpr(r)
    return f'{reg} = (uint{w}_t)({expr});'

def getg(r):
    reg, w = gpr(r)
    return reg if w == 64 else f'(uint32_t){reg}'

def vreg(r):
    m = re.fullmatch(r'([xy])mm(\d+)', r)
    assert m, r
    return int(m.group(2)), 32 if m.group(1) == 'y' else 16

def isv(op):
    return re.fullmatch(r'[xy]mm\d+', op) is not None

def imm(s):
    return int(s, 0)

def split_ops(ops):
    res, depth, cur = [], 0, ''
    for c in ops:
        depth += (c == '[') - (c == ']')
        if c == ',' and depth == 0:
            res.append(cur.strip()); cur = ''
        else:
            cur += c
    if cur.strip():
        res.append(cur.strip())
    return res

def symexpr(sym, addend):
    m = re.fullmatch(r'(\.rodata|ff_tx_tab_\w+)([+-]0x[0-9a-f]+)?', sym)
    assert m, sym
    off = addend + int(m.group(2) or '0', 16)
    base = '(const uint8_t*)kRodata' if m.group(1) == '.rodata' else f'(const uint8_t*){m.group(1)}'
    return f'({base} + {off})'

def mem(op, insn):
    """Memory operand -> (C address expression, size, vector index or None)."""
    m = re.fullmatch(r'(?:(byte|word|dword|qword|xmmword|ymmword) ptr )?\[([^\]]*)\]', op)
    assert m, op
    size = {'dword': 4, 'qword': 8, 'xmmword': 16, 'ymmword': 32, None: 0}[m.group(1)]
    terms = re.findall(r'([+-]?)\s*([^+-]+)', m.group(2))
    parts, vidx = [], None
    for sign, t in terms:
        t = t.strip()
        if t == 'rip':
            off, sym = insn[3]
            parts.append(f'(uintptr_t){symexpr(sym, nexta[insn[0]] - off)}')
        elif re.fullmatch(r'-?0x[0-9a-f]+|\d+', t):
            parts.append(f'{sign}{imm(t)}')
        else:
            sc, _, r = t.rpartition('*')
            sc = int(sc) if sc else 1
            if isv(r):
                vidx = (vreg(r)[0], sc)
            else:
                assert sign != '-', op
                parts.append(f'{getg(r)} * {sc}' if sc != 1 else getg(r))
    if insn[3]:
        assert any('kRodata' in p or 'ff_tx_tab' in p for p in parts), insn
    return '(uint8_t*)(' + ' + '.join(parts).replace('+ -', '- ') + ')', size, vidx

def src(op, insn):
    """Vector source operand: register or a load."""
    if isv(op):
        return f'R->y[{vreg(op)[0]}]'
    a, size, _ = mem(op, insn)
    return f'ld{size}({a})'

used = set()

def vex(d, w, expr):
    """A VEX write: an xmm destination clears bits 255:128."""
    return f'R->y[{d}] = {expr};' if w == 32 else f'R->y[{d}] = lo({expr});'

def legacy(d, expr):
    """A legacy SSE write keeps bits 255:128."""
    return f'R->y[{d}] = keephi(R->y[{d}], {expr});'

# Flags are computed only where a conditional jump reads them.
FLAG_WRITERS = {'add', 'sub', 'cmp', 'and', 'neg', 'xor', 'shl', 'imul'}
flag_needed = set()
for i, (a, mn, ops, r) in enumerate(insns):
    if mn in ('jg', 'je', 'jge'):
        j = i - 1
        while insns[j][1] not in FLAG_WRITERS:
            assert insns[j][0] not in syms, insns[i]
            j -= 1
        assert insns[j][1] in ('add', 'sub', 'cmp'), (insns[j], insns[i])
        flag_needed.add(insns[j][0])

retsites = []
CC = {'jg': '!F_Z && F_S == F_O', 'je': 'F_Z', 'jge': 'F_S == F_O'}
LANEOPS = {'vaddps': 'addps', 'vsubps': 'subps', 'vmulps': 'mulps', 'vaddsubps': 'addsubps',
           'vxorps': 'xorps', 'vunpcklpd': 'unpcklpd', 'vunpckhpd': 'unpckhpd',
           'vunpcklps': 'unpcklps', 'vunpckhps': 'unpckhps', 'vpcmpeqd': 'pcmpeqd',
           'vpsubd': 'psubd', 'vpmulld': 'pmulld', 'vpermilps': 'permilps', 'vmovlhps': 'movlhps'}

def tr(insn):
    a, mn, ops, rel = insn
    o = split_ops(ops)
    if mn in ('nop', 'vzeroupper'):
        return '' if mn == 'nop' else 'for (int i_ = 0; i_ < 16; i_++) R->y[i_] = lo(R->y[i_]);'
    if mn == 'ret':
        return 'RET();'
    if mn == 'jmp':
        return f'goto L_{int(o[0].split()[0], 16):x};'
    if mn in CC:
        return f'if ({CC[mn]}) goto L_{int(o[0].split()[0], 16):x};'
    if mn == 'call':
        retsites.append(a)
        k = len(retsites)
        if o[0] in GPR:
            arms = ' else '.join(f'if (t_ == (uintptr_t)&{syms[e]}) CALL(L_{e:x}, {k});' for e in entries)
            return f'{{ uintptr_t t_ = {getg(o[0])}; {arms} else abort(); }}'
        return f'CALL(L_{int(o[0].split()[0], 16):x}, {k});'
    if mn == 'push':
        return f'R->r[4] -= 8; memcpy((void*)R->r[4], &{gpr(o[0])[0]}, 8);'
    if mn == 'pop':
        return f'memcpy(&{gpr(o[0])[0]}, (void*)R->r[4], 8); R->r[4] += 8;'
    if mn in ('mov', 'movsxd', 'lea') and not isv(o[0]):
        d, s = o
        if mn == 'lea':
            return setg(d, mem(s, insn)[0][len('(uint8_t*)'):])
        if s.startswith('[') or 'ptr' in s:
            A, size, _ = mem(s, insn)
            if mn == 'movsxd':
                return f'{{ int32_t t_; memcpy(&t_, {A}, 4); {setg(d, "(int64_t)t_")} }}'
            T = {4: 'uint32_t', 8: 'uint64_t'}[size]
            return f'{{ {T} t_; memcpy(&t_, {A}, {size}); {setg(d, "t_")} }}'
        if re.fullmatch(r'-?0x[0-9a-f]+|\d+', s):
            return setg(d, f'(int64_t){imm(s)}')
        return setg(d, getg(s))
    if mn in ('add', 'sub', 'cmp', 'and', 'xor', 'neg', 'shl', 'imul'):
        d = o[0]
        reg, w = gpr(d)
        T, S = f'uint{w}_t', f'int{w}_t'
        if mn == 'neg':
            return setg(d, f'-{getg(d)}')
        if mn == 'shl':
            return setg(d, f'{getg(d)} << {imm(o[1]) if len(o) > 1 else 1}')
        if mn == 'imul':
            if len(o) == 3:
                return setg(d, f'{getg(o[1])} * {imm(o[2])}')
            return setg(d, f'{getg(d)} * {getg(o[1])}')
        b = getg(o[1]) if o[1] in GPR + GPR32 else f'({T})(int64_t){imm(o[1])}'
        op = {'add': '+', 'sub': '-', 'cmp': '-', 'and': '&', 'xor': '^'}[mn]
        code = f'{{ {T} a_ = {getg(d)}, b_ = {b}, r_ = a_ {op} b_; '
        if a in flag_needed:
            ov = (f'((({S})a_ < 0) == (({S})b_ < 0)) && ((({S})r_ < 0) != (({S})a_ < 0))' if mn == 'add' else
                  f'((({S})a_ < 0) != (({S})b_ < 0)) && ((({S})r_ < 0) != (({S})a_ < 0))')
            code += f'F_Z = r_ == 0; F_S = ({S})r_ < 0; F_O = {ov}; '
        if mn != 'cmp':
            code += f'{reg} = r_; '
        return code + '}'

    # Vector moves.
    if mn in ('vmovaps', 'vmovups', 'vmovupd', 'movaps', 'movups'):
        d, s = o
        if not isv(d):
            A, size, _ = mem(d, insn)
            return f'memcpy({A}, &R->y[{vreg(s)[0]}], {size});'
        n, w = vreg(d)
        if mn.startswith('v'):
            return vex(n, w, src(s, insn))
        return legacy(n, src(s, insn))
    if mn in ('vmovsd', 'movsd'):
        n, _ = vreg(o[0])
        A, size, _ = mem(o[1], insn)
        assert size == 8
        return vex(n, 16, f'ld8({A})') if mn == 'vmovsd' else legacy(n, f'ld8({A})')
    if mn in ('vmovhps', 'vmovlps', 'movhps'):
        if not isv(o[0]):
            A, _, _ = mem(o[0], insn)
            return f'memcpy({A}, &R->y[{vreg(o[1])[0]}].d[{int(mn == "vmovhps")}], 8);'
        n, _ = vreg(o[0])
        A, _, _ = mem(o[-1], insn)
        base = f'R->y[{vreg(o[1])[0]}]' if mn == 'vmovhps' else f'R->y[{n}]'
        expr = f'sethi({base}, {A})'
        return vex(n, 16, expr) if mn == 'vmovhps' else legacy(n, expr)
    if mn == 'vmovddup':
        n, _ = vreg(o[0])
        A, _, _ = mem(o[1], insn)
        return vex(n, 16, f'movddup(ld8({A}))')
    if mn == 'vmovd':
        n, _ = vreg(o[0])
        return f'memset(&R->y[{n}], 0, 32); R->y[{n}].s[0] = {getg(o[1])};'
    if mn == 'vextractf128':
        n, w = vreg(o[1])
        h = imm(o[2]) & 1
        if isv(o[0]):
            return f'R->y[{vreg(o[0])[0]}] = half(R->y[{n}], {h});'
        A, _, _ = mem(o[0], insn)
        return f'memcpy({A}, &R->y[{n}].b[{16 * h}], 16);'
    if mn in ('vmovshdup', 'vmovsldup', 'vbroadcastsd', 'vpbroadcastd'):
        n, w = vreg(o[0])
        f = mn[1:]
        used.add(f)
        return vex(n, w, f'{f}({src(o[1], insn)})')
    if mn in ('vgatherdpd', 'vgatherdps'):
        n, w = vreg(o[0])
        mk, _ = vreg(o[2])
        A, _, (ix, sc) = mem(o[1], insn)
        k = (w // 8) if mn == 'vgatherdpd' else (w // 4)
        T, f = ('uint64_t', 'd') if mn == 'vgatherdpd' else ('uint32_t', 's')
        bits = 64 if f == 'd' else 32
        return (f'for (int i_ = 0; i_ < {k}; i_++) if (R->y[{mk}].{f}[i_] >> {bits - 1}) '
                f'memcpy(&R->y[{n}].{f}[i_], {A} + (int64_t)R->y[{ix}].i[i_] * {sc}, {bits // 8}); '
                + ('' if w == 32 else f'R->y[{n}] = lo(R->y[{n}]); ') + f'memset(&R->y[{mk}], 0, 32);')

    # Vector arithmetic and shuffles.
    if mn in ('vfmaddsub213ps', 'vfmsubadd213ps', 'vfmaddsub231ps', 'vfmadd132ps'):
        n, w = vreg(o[0])
        d, s2, s3 = f'R->y[{n}]', src(o[1], insn), src(o[2], insn)
        f = mn[1:-5]
        used.add(f)
        args = {'213': (s2, d, s3), '231': (s2, s3, d), '132': (d, s3, s2)}[mn[-5:-2]]
        return vex(n, w, f'{f}({", ".join(args)})')
    if mn in LANEOPS or mn in ('vshufps', 'vshufpd', 'vperm2f128', 'vinsertf128', 'vblendps', 'vpermps'):
        n, w = vreg(o[0])
        f = LANEOPS.get(mn, mn[1:])
        used.add(f)
        args = [src(x, insn) for x in o[1:3]] + [str(imm(x)) for x in o[3:]]
        return vex(n, w, f'{f}({", ".join(args)})')
    if mn == 'vpermpd':
        n, w = vreg(o[0])
        used.add('permpd')
        return vex(n, w, f'permpd({src(o[1], insn)}, {imm(o[2])})')
    if mn in ('addps', 'subps', 'mulps', 'addsubps', 'xorps', 'unpcklpd', 'unpckhpd', 'shufps'):
        n, _ = vreg(o[0])
        used.add(mn)
        args = [f'R->y[{n}]', src(o[1], insn)] + [str(imm(x)) for x in o[2:]]
        return legacy(n, f'{mn}({", ".join(args)})')
    raise SystemExit(f'unhandled {a:x}: {mn} {ops}')

targets = set()
for a, mn, ops, r in insns:
    if mn in ('jmp', 'call') + tuple(CC) and not ops in GPR:
        targets.add(int(ops.split()[0], 16))

body = []
for insn in insns:
    a, mn, ops, _ = insn
    lab = f'L_{a:x}: ' if a in targets or a in syms else ''
    code = tr(insn)
    if a in syms:
        body.append(f'  /* {syms[a]} */')
    body.append(f'  {lab}{code}  /* {a:x}: {mn} {ops} */' if lab or code else f'  /* {a:x}: {mn} */')
    if mn == 'call':
        body.append(f'  R_{len(retsites)}:;')

tabs = sorted({re.sub(r'[+-].*', '', r[1]) for _, _, _, r in insns if r and r[1].startswith('ff_tx_tab_')})

HELPERS = {
    'addps': 'static inline YV addps(YV a, YV b) LANES8(f, a.f[i] + b.f[i])',
    'subps': 'static inline YV subps(YV a, YV b) LANES8(f, a.f[i] - b.f[i])',
    'mulps': 'static inline YV mulps(YV a, YV b) LANES8(f, a.f[i] * b.f[i])',
    'addsubps': 'static inline YV addsubps(YV a, YV b) LANES8(f, (i & 1) ? a.f[i] + b.f[i] : a.f[i] - b.f[i])',
    'xorps': 'static inline YV xorps(YV a, YV b) LANES8(s, a.s[i] ^ b.s[i])',
    'pcmpeqd': 'static inline YV pcmpeqd(YV a, YV b) LANES8(s, a.s[i] == b.s[i] ? 0xffffffffu : 0)',
    'psubd': 'static inline YV psubd(YV a, YV b) LANES8(s, a.s[i] - b.s[i])',
    'pmulld': 'static inline YV pmulld(YV a, YV b) LANES8(s, a.s[i] * b.s[i])',
    'fmaddsub': 'static inline YV fmaddsub(YV a, YV b, YV c) LANES8(f, fmaf(a.f[i], b.f[i], (i & 1) ? c.f[i] : -c.f[i]))',
    'fmsubadd': 'static inline YV fmsubadd(YV a, YV b, YV c) LANES8(f, fmaf(a.f[i], b.f[i], (i & 1) ? -c.f[i] : c.f[i]))',
    'fmadd': 'static inline YV fmadd(YV a, YV b, YV c) LANES8(f, fmaf(a.f[i], b.f[i], c.f[i]))',
    'movshdup': 'static inline YV movshdup(YV a) LANES8(s, a.s[i | 1])',
    'movsldup': 'static inline YV movsldup(YV a) LANES8(s, a.s[i & ~1])',
    'pbroadcastd': 'static inline YV pbroadcastd(YV a) LANES8(s, a.s[0])',
    'permilps': 'static inline YV permilps(YV a, YV c) LANES8(s, a.s[(i & 4) | (c.s[i] & 3)])',
    'permps': 'static inline YV permps(YV idx, YV a) LANES8(s, a.s[idx.s[i] & 7])',
    'blendps': 'static inline YV blendps(YV a, YV b, int k) LANES8(s, (k >> i) & 1 ? b.s[i] : a.s[i])',
    'shufps': 'static inline YV shufps(YV a, YV b, int k) LANES8(s, (i & 2 ? b : a).s[(i & 4) | ((k >> (2 * (i & 3))) & 3)])',
    'unpcklps': 'static inline YV unpcklps(YV a, YV b) LANES8(s, (i & 1 ? b : a).s[(i & 4) | ((i & 3) >> 1)])',
    'unpckhps': 'static inline YV unpckhps(YV a, YV b) LANES8(s, (i & 1 ? b : a).s[(i & 4) | 2 | ((i & 3) >> 1)])',
    'unpcklpd': 'static inline YV unpcklpd(YV a, YV b) LANES4(d, (i & 1 ? b : a).d[i & 2])',
    'unpckhpd': 'static inline YV unpckhpd(YV a, YV b) LANES4(d, (i & 1 ? b : a).d[(i & 2) | 1])',
    'shufpd': 'static inline YV shufpd(YV a, YV b, int k) LANES4(d, (i & 1 ? b : a).d[(i & 2) | ((k >> i) & 1)])',
    'movlhps': 'static inline YV movlhps(YV a, YV b) LANES4(d, i == 0 ? a.d[0] : b.d[0])',
    'broadcastsd': 'static inline YV broadcastsd(YV a) LANES4(d, a.d[0])',
    'permpd': 'static inline YV permpd(YV a, int k) LANES4(d, a.d[(k >> (2 * i)) & 3])',
    'perm2f128': 'static inline YV perm2f128(YV a, YV b, int k) LANES4(d, (k >> (4 * (i >> 1))) & 8 ? 0 : '
                 '(((k >> (4 * (i >> 1))) & 2) ? b : a).d[(((k >> (4 * (i >> 1))) & 1) << 1) | (i & 1)])',
    'insertf128': 'static inline YV insertf128(YV a, YV b, int k) LANES4(d, (i >> 1) == (k & 1) ? b.d[i & 1] : a.d[i])',
}

print('''/* Generated by x86toc.py from libavutil/x86/tx_float.asm (FFmpeg, LGPL 2.1
 * or later, Copyright (c) Lynne). Do not edit: regenerate.
 *
 * general.cpu_identity = Intel or AMD on ARM64: the x86 FFT codelets an
 * AVX2/FMA3 CPU runs, executed instruction for instruction on an emulated
 * x86-64 register file, so a transform returns the bits an x86 CPU's would.
 * The FMA3 forms are fused (fmaf), every other float operation is one IEEE
 * single-precision rounding, as on x86. NaN payload and sign propagation
 * follow ARM, not x86.
 */

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifdef X86EMU_STANDALONE
typedef struct AVTXContext AVTXContext;
#else
#define TX_FLOAT
#include "libavutil/tx_priv.h"
#include "libavutil/attributes.h"
#endif

typedef union {
    float f[8];
    uint32_t s[8];
    int32_t i[8];
    uint64_t d[4];
    uint8_t b[32];
} YV;

typedef struct {
    uint64_t r[16]; /* rax, rcx, rdx, rbx, rsp, rbp, rsi, rdi, r8-r15 */
    YV y[16];
} XRegs;
''')
for t in tabs:
    print(f'extern const float {t}[];')
print('static const uint8_t kRodata[%d] __attribute__((aligned(32))) = {%s};' % (len(rod), ', '.join(str(b) for b in rod)))
print(r'''
#define LANES8(t, expr) { YV r_; for (int i = 0; i < 8; i++) r_.t[i] = (expr); return r_; }
#define LANES4(t, expr) { YV r_; for (int i = 0; i < 4; i++) r_.t[i] = (expr); return r_; }
static inline YV ld32(const uint8_t* p) { YV r_; memcpy(&r_, p, 32); return r_; }
static inline YV ld16(const uint8_t* p) { YV r_; memset(&r_, 0, 32); memcpy(&r_, p, 16); return r_; }
static inline YV ld8(const uint8_t* p) { YV r_; memset(&r_, 0, 32); memcpy(&r_, p, 8); return r_; }
static inline YV lo(YV a) { a.d[2] = a.d[3] = 0; return a; }
static inline YV keephi(YV old, YV a) { a.d[2] = old.d[2]; a.d[3] = old.d[3]; return a; }
static inline YV half(YV a, int h) { YV r_; memset(&r_, 0, 32); r_.d[0] = a.d[2 * h]; r_.d[1] = a.d[2 * h + 1]; return r_; }
static inline YV sethi(YV a, const uint8_t* p) { memcpy(&a.d[1], p, 8); return a; }
static inline YV movddup(YV a) { a.d[1] = a.d[0]; return a; }''')
for k, v in HELPERS.items():
    if k in used:
        print(v)
missing = used - set(HELPERS)
assert not missing, missing
print(r'''
#define CALL(target, k) do { uint64_t k_ = (k); R->r[4] -= 8; memcpy((void*)R->r[4], &k_, 8); goto target; } while (0)
#define RET() do { uint64_t k_; memcpy(&k_, (void*)R->r[4], 8); R->r[4] += 8; if (k_ == 0) return; goto *RS[k_]; } while (0)
''')
for e in entries:
    print(f'void {syms[e]}(AVTXContext* s, void* out, void* in, ptrdiff_t stride);')
print('''
static void x86emu_run(int entry, XRegs* R) {
    static void* const RS[] = { 0, %s };
    int F_Z = 0, F_S = 0, F_O = 0;
    (void)F_S; (void)F_O;
    switch (entry) {''' % ', '.join(f'&&R_{k}' for k in range(1, len(retsites) + 1)))
for i, a in enumerate(entries):
    print(f'      case {i}: goto L_{a:x};')
print('      default: return;\n    }')
print('\n'.join(body))
print('}\n')
print('''static void x86emu_call(int entry, AVTXContext* s, void* out, void* in,
                        ptrdiff_t stride) {
    XRegs R;
    uint64_t stack[512] __attribute__((aligned(32)));
    uint64_t ret = 0;
    memset(&R, 0, sizeof(R));
    R.r[7] = (uintptr_t)s;      /* rdi */
    R.r[6] = (uintptr_t)out;    /* rsi */
    R.r[2] = (uintptr_t)in;     /* rdx */
    R.r[1] = (uint64_t)stride;  /* rcx */
    R.r[4] = (uintptr_t)(stack + 512) - 8;
    memcpy((void*)R.r[4], &ret, 8);
    x86emu_run(entry, &R);
}
''')
for i, a in enumerate(entries):
    print(f'void {syms[a]}(AVTXContext* s, void* out, void* in, ptrdiff_t stride) {{ x86emu_call({i}, s, out, in, stride); }}')

print(r'''
#ifndef X86EMU_STANDALONE
/* The codelet list of x86/tx_float_init.c, built here around the emulated
 * functions. tx.c uses it, with the CPU flags of an AVX2/FMA3 CPU, instead
 * of the aarch64 list while av_tx_cfp_emulate_x86(1) is in effect. */
#undef ARCH_X86_64
#define ARCH_X86_64 1
#define ff_tx_codelet_list_float_x86 ff_tx_codelet_list_float_x86emu
#include "libavutil/x86/tx_float_init.c"
#endif''')
