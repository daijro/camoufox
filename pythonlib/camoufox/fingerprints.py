import hashlib
import json
import os
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from random import Random, choice, randint, randrange
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from camoufox._warnings import FallbackWarning
from camoufox.ip import valid_ipv4, validate_ip
from camoufox.pkgman import load_yaml

# Load the fpgen mapping file
FPGEN_DATA = load_yaml('fpgen.yml')

# fpgen's OS names, from Camoufox's.
_FPGEN_OS = {'lin': 'Linux', 'linux': 'Linux', 'mac': 'macOS', 'macos': 'macOS',
             'win': 'Windows', 'windows': 'Windows'}

# fpgen unpacks ~7 MB of model data on first use, so the generator is built on
# demand rather than at import: `import camoufox` must stay cheap for callers
# who never generate a fingerprint (they passed their own, or a preset).
_FP_GENERATOR = None


def _generator():
    global _FP_GENERATOR
    if _FP_GENERATOR is None:
        from .fpgen_model import load_fpgen

        _FP_GENERATOR = load_fpgen().Generator()
    return _FP_GENERATOR


@dataclass
class Screen:
    """A bound on the screen a generated fingerprint may claim.

    Replaces browserforge.fingerprints.Screen, which left with the BrowserForge
    dependency. Same four fields, same meaning: the generated screen must fit
    inside them.
    """

    min_width: Optional[int] = None
    max_width: Optional[int] = None
    min_height: Optional[int] = None
    max_height: Optional[int] = None

    def as_conditions(self) -> Dict[str, Any]:
        """The bound, as fpgen conditions.

        fpgen takes a predicate per field and rejects a value the predicate
        refuses, so a range is a closure rather than a list of allowed values.
        """
        conditions: Dict[str, Any] = {}
        lo_w, hi_w = self.min_width, self.max_width
        lo_h, hi_h = self.min_height, self.max_height
        if lo_w is not None or hi_w is not None:
            conditions['screen.width'] = lambda w: (
                isinstance(w, int) and (lo_w is None or w >= lo_w) and (hi_w is None or w <= hi_w)
            )
        if lo_h is not None or hi_h is not None:
            conditions['screen.height'] = lambda h: (
                isinstance(h, int) and (lo_h is None or h >= lo_h) and (hi_h is None or h <= hi_h)
            )
        return conditions

# Bundled real fingerprint presets
PRESETS_FILE = Path(__file__).parent / 'fingerprint-presets.json'
PRESETS_V150_FILE = Path(__file__).parent / 'fingerprint-presets-v150.json'
# Firefox major version at which the v150 preset bundle becomes preferred.
PRESETS_V150_MIN_FF = 149
_PRESETS_CACHE: Dict[Path, Dict] = {}

# CreepJS OS marker fonts used for OS detection. Twin of MARKER_FONTS in
# scripts/gen-fonts-json.py. Every name must be in fonts.json for its OS
# (scripts/verify-fonts.py checks): a marker the bundle cannot render would be a
# reverse leak. That is why PingFang HK/SC/TC are no longer macOS markers -- the
# bundle carries no PingFang file. On Linux the first three are also
# the families bundle/fontconfig/linux/fonts.conf resolves sans-serif / serif /
# monospace to, so an identity without them would have no face behind any CSS
# generic; Arimo / Cousine / Tinos stay because a real Ubuntu answers "present"
# for them via its metric aliases.
_MACOS_MARKER_FONTS = [
    'Helvetica Neue',
]
_LINUX_MARKER_FONTS = [
    'Noto Sans', 'Noto Serif', 'DejaVu Sans Mono', 'Arimo', 'Cousine', 'Tinos', 'Twemoji Mozilla',
]
_WINDOWS_MARKER_FONTS = [
    'Segoe UI', 'Tahoma', 'Cambria Math', 'Nirmala UI',
]


def _ensure_marker_fonts(fonts: List[str], markers: List[str]) -> None:
    """Add any missing marker fonts to the font list (in-place)."""
    existing = set(fonts)
    for m in markers:
        if m not in existing:
            fonts.append(m)


# OS font lists loaded from fonts.json
_OS_FONTS_CACHE: Optional[Dict[str, List[str]]] = None

def _load_os_fonts() -> Dict[str, List[str]]:
    """Load the full OS font lists from fonts.json."""
    global _OS_FONTS_CACHE
    if _OS_FONTS_CACHE is not None:
        return _OS_FONTS_CACHE
    fonts_path = os.path.join(os.path.dirname(__file__), 'fonts.json')
    with open(fonts_path, 'rb') as f:
        import orjson
        _OS_FONTS_CACHE = orjson.loads(f.read())
    return _OS_FONTS_CACHE


# Essential fonts per OS that must always be included in subsets.
#
# These are the OS BASE font sets: every family a real machine of that OS ships
# by default. A real machine has ALL of its OS defaults -- only the additions
# (Office, LibreOffice, Adobe CC, developer and web fonts) vary from box to box --
# so the base is never subsetted; the random 30-78% draw below applies to the
# additions only (fonts.json minus the base).
#
# Source: the per-OS bases in scripts/data/font-manifests.json (Windows 10 with
# the stock CJK families; macOS Sonoma; Ubuntu and its Mint variant),
# intersected with fonts.json so only names the bundle can
# render are listed (Sonoma's PingFang / Kefa / Hiragino families are in the real
# base but not bundled, so they are absent here). They live in essential-fonts.json,
# which the TypeScript launcher reads too; regenerate it together with fonts.json:
# `python3 scripts/gen-fonts-json.py --print-bases`.
#
# Windows: the seven GDI-substitution names (Courier, Helvetica, MS Sans Serif,
# MS Serif, Roman, Small Fonts, Times) and the six Light/Semilight names have no
# file of their own; bundle/fontconfig/windows/fonts.conf rewrites each to its
# bundled target unconditionally, so they MUST stay in this always-reported set
# (an identity that did not report Helvetica would still render it otherwise).
with open(os.path.join(os.path.dirname(__file__), 'essential-fonts.json'), 'rb') as _f:
    _ESSENTIAL = json.loads(_f.read())
_ESSENTIAL_FONTS_WINDOWS: List[str] = _ESSENTIAL['win']
_ESSENTIAL_FONTS_MACOS: List[str] = _ESSENTIAL['mac']
_ESSENTIAL_FONTS_LINUX: List[str] = _ESSENTIAL['lin']

# OS-version variants of the base, drawn ALL-OR-NOTHING on top of the essential
# core with the real-world share of that version (the manifest's base weights). A
# Windows 11 machine (65%) has every one of the Win11 additions and a Windows 10
# machine none of them; Ubuntu (65%) ships Liberation Sans Narrow, Mint (35%)
# does not. macOS has a single bundled base (Sonoma). Format: (probability, fonts).
_BASE_VARIANT_FONTS_MACOS = (0.0, [])
_BASE_VARIANT_FONTS_WINDOWS = (1.0, [
    # Verified present on win-i9 (real Windows 11 build 26200.9457). Windows 10
    # was dropped 2026-09-22 (end of support Oct 2025), so every Windows identity
    # is Windows 11 and these are always drawn. Cascadia Code/Mono are NOT here:
    # they are not on a stock Windows 11 and are modelled as an addition.
    'Sans Serif Collection', 'Segoe Fluent Icons', 'Segoe UI Variable',
    'Segoe UI Variable Display', 'Segoe UI Variable Small', 'Segoe UI Variable Text',
])
# Linux needs no variant: both shipped bases are exact, whole font sets taken
# from the official Ubuntu 24.04 / 26.04 desktop ISO manifests, and
# fonts-liberation-sans-narrow is in both of them.
_BASE_VARIANT_FONTS_LINUX = (0.0, [])

# Fonts only a Windows 11 base has: a Windows identity whose font list contains
# them presents Windows 11, and the rest of the identity (overlay scrollbars,
# utils.launch_options) must agree.
WINDOWS_11_MARKER_FONTS = frozenset(_BASE_VARIANT_FONTS_WINDOWS[1])



def identity_salt(pinned: Any = None) -> int:
    """The entropy that makes identity_seed() belong to ONE identity.

    The presented values identity_seed() hashes are shared by many unrelated
    launches: browserforge gives each OS only a handful of screens and UAs, so
    over 500 launches per OS the unsalted seed took 12-30 distinct values, and
    every Camoufox install everywhere drew its fonts, voices, GPU, media devices
    and canvas/audio noise seeds from that same short list.

    Pass whatever the caller pinned the identity with -- a browserforge
    Fingerprint, a preset dict, the caller's own config -- to get a salt that
    is stable across launches of that identity (daijro/camoufox#442, #765);
    pass nothing for a fresh identity, which gets a random salt.
    """
    if pinned is None:
        return secrets.randbits(64)
    if is_dataclass(pinned) and not isinstance(pinned, type):
        pinned = asdict(pinned)
    import orjson

    blob = orjson.dumps(pinned, option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS, default=str)
    return int.from_bytes(hashlib.sha256(blob).digest()[:8], 'big')


def identity_seed(config: Dict[str, Any], salt: int = 0) -> int:
    """A seed for the per-identity draws (fonts, voices, GPU, media devices,
    noise seeds): a pure function of the presented identity and its salt.

    Two launches that present the same identity must present the same font and
    voice lists: a page that keeps cookies across launches and sees the font
    set or the voice list change under an otherwise identical device reads it
    as a spoofed browser (daijro/camoufox#442, #765, #378). The presented
    values alone are far too common to tell identities apart, so callers mix in
    identity_salt() (see there).
    """
    import zlib
    parts = [
        str(config.get('navigator.userAgent', '')),
        str(config.get('navigator.platform', '')),
        str(config.get('screen.width', '')),
        str(config.get('screen.height', '')),
        str(config.get('navigator.hardwareConcurrency', '')),
        # not the GPU: it is sampled after the font draw in launch_options
        str(salt),
    ]
    return zlib.crc32('|'.join(parts).encode('utf-8')) & 0xFFFFFFFF


def _rng(seed: Optional[int]) -> Random:
    """Seeded generator for a draw, or the module-level one when unseeded."""
    return Random(seed) if seed is not None else Random()


_FONT_GROUPS_CACHE: Optional[Dict[str, List[Dict[str, Any]]]] = None


def _load_font_groups() -> Dict[str, List[Dict[str, Any]]]:
    """The addition units per OS (font-groups.json, generated from the manifest
    by scripts/gen-font-groups.py). Each entry is

        {"id", "kind", "prob", "fonts", ["requiresLocale"], ["sizes"]}

    and carries its OWN real-world probability, because that is what makes a
    drawn machine plausible: Office is on ~60% of Windows boxes and the
    Pan-European supplemental pack on ~2.8%, and a draw that treated them alike
    would put a font nobody has on a third of its identities."""
    global _FONT_GROUPS_CACHE
    if _FONT_GROUPS_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), 'font-groups.json')
        try:
            with open(path, 'rb') as f:
                _FONT_GROUPS_CACHE = json.loads(f.read())
        except (OSError, ValueError) as e:
            FallbackWarning.warn(
                'Reading font-groups.json', 'an OS-version base with no font additions', e
            )
            _FONT_GROUPS_CACHE = {}
    return _FONT_GROUPS_CACHE


_FONT_BASES_CACHE: Optional[Dict[str, List[Dict[str, Any]]]] = None


def _load_font_bases() -> Dict[str, List[Dict[str, Any]]]:
    """The OS-VERSION bases per OS (font-bases.json, same generator).

    One machine runs one OS version and has that version's whole default font
    set, so a base is drawn entire, by weight, and never subsetted. Windows 11's
    base happens to be Windows 10's plus a few families, but macOS 26's is not a
    superset of Sonoma's -- Apple renamed Kefa to "Kefa III", added PingFang MO
    and respelled several Noto families (measured on macOS 26.6.2, build 25G83)
    -- so they are alternatives, not a core plus extras."""
    global _FONT_BASES_CACHE
    if _FONT_BASES_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), 'font-bases.json')
        try:
            with open(path, 'rb') as f:
                _FONT_BASES_CACHE = json.loads(f.read())
        except (OSError, ValueError) as e:
            FallbackWarning.warn(
                'Reading font-bases.json', 'only the always-present core fonts as its OS base', e
            )
            _FONT_BASES_CACHE = {}
    return _FONT_BASES_CACHE


def _pick_base(os_key: str, rng: Any) -> List[str]:
    """Draw one OS-version base by its real-world weight."""
    bases = _load_font_bases().get(os_key) or []
    if not bases:
        return []
    roll = rng.random()
    cumulative = 0.0
    for base in bases:
        cumulative += base.get('weight', 0.0)
        if roll < cumulative:
            return list(base['fonts'])
    return list(bases[-1]['fonts'])


def _draw_units(os_key: str, rng: Any, exclude: Set[str],
                locale: Optional[str] = None) -> List[str]:
    """The additions this machine has, each unit judged on its own probability.

    A "bundle" unit is all-or-nothing: the software either installed its fonts
    or it did not. An "alacarte" unit is a category people install piecemeal, so
    it first has to be present at all and then contributes `sizes` of its
    members -- which is what stops a draw from reporting all 32 web fonts or
    none, neither of which is what a real machine looks like.
    """
    out: List[str] = []
    for unit in _load_font_groups().get(os_key, []):
        required = unit.get('requiresLocale')
        if required and not (locale or '').lower().startswith(required.lower()):
            # e.g. the Traditional-Chinese supplemental pack is on ~90% of zh-TW
            # machines and essentially no others; claiming it on an en-US
            # identity is the kind of mismatch a WAF checks for.
            continue
        if rng.random() >= unit.get('prob', 0.0):
            continue
        members = [f for f in unit['fonts'] if f not in exclude]
        if not members:
            continue
        if unit['kind'] == 'alacarte':
            sizes = unit.get('sizes') or [{'n': len(members), 'w': 1.0}]
            roll = rng.random() * sum(s['w'] for s in sizes)
            cumulative = 0.0
            count = sizes[-1]['n']
            for size in sizes:
                cumulative += size['w']
                if roll < cumulative:
                    count = size['n']
                    break
            count = max(1, min(count, len(members)))
            members = rng.sample(members, count)
        out.extend(members)
    return out


def _host_has_variant_fonts(target_os: str) -> bool:
    """Whether the host itself ships the OS-version font variant (native identities only)."""
    if target_os != 'windows':
        return False
    import os
    fonts_dir = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
    # SegUIVar.ttf is Segoe UI Variable, present on every Windows 11 install and on no Windows 10.
    return os.path.exists(os.path.join(fonts_dir, 'SegUIVar.ttf'))


def _generate_random_font_subset(
    target_os: str,
    seed: Optional[int] = None,
    native: bool = False,
    locale: Optional[str] = None,
) -> List[str]:
    """
    Generate the font list of one plausible machine of the given OS.

    A real machine is one OS-version base plus whatever software the owner
    installed, so that is how this draws: one base by weight, in full and never
    subsetted, then each addition unit independently at its own measured
    probability (font-groups.json). The marker fonts are ensured last.

    `locale` gates the units a manifest marks `requiresLocale` -- the
    Traditional-Chinese supplemental pack is on ~90% of zh-TW machines and
    almost no others, so claiming it on an en-US identity is a mismatch a WAF
    can check.

    `native`: the identity is the host's own OS (macOS / Windows), where the
    browser uses the real system fonts and not the bundle. Only the OS base
    is claimed then: an "addition" the host does not have would be listed but
    fall back when measured, which a page can see (measured 2026-09-14 on a
    stock Mac mini: Fira Code / Lato claimed, rendered as Menlo).
    """
    rng = _rng(seed)
    os_fonts_data = _load_os_fonts()
    os_key = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}.get(target_os, 'mac')
    full_list = os_fonts_data.get(os_key, os_fonts_data.get('mac', []))

    if target_os == 'windows':
        essential = set(_ESSENTIAL_FONTS_WINDOWS)
        markers = _WINDOWS_MARKER_FONTS
        variant_prob, variant_fonts = _BASE_VARIANT_FONTS_WINDOWS
    elif target_os == 'linux':
        essential = set(_ESSENTIAL_FONTS_LINUX)
        markers = _LINUX_MARKER_FONTS
        variant_prob, variant_fonts = _BASE_VARIANT_FONTS_LINUX
    else:
        essential = set(_ESSENTIAL_FONTS_MACOS)
        markers = _MACOS_MARKER_FONTS
        variant_prob, variant_fonts = _BASE_VARIANT_FONTS_MACOS
    variant = set(variant_fonts)

    if native:
        # The host's own OS: the browser is using the real system fonts, so the
        # claim is the base and nothing else. An "addition" the host does not
        # have would be listed and then fall back when measured, which a page
        # can see (measured 2026-09-14 on a stock Mac mini: Fira Code / Lato
        # claimed, rendered as Menlo).
        result = [f for f in full_list if f in essential]
        result.extend(sorted(f for f in essential if f not in set(full_list)))
        # The OS-version variant is real system fonts too: claim it exactly when
        # the host has it. A Windows 11 host presented as Windows 10 hides Segoe UI
        # Variable etc. and, with the matching classic scrollbars, differs from the
        # stock Firefox on the same machine (Windows 11 test host, 2026-09-16:
        # 0 px overlay).
        # Windows 10 was dropped as a spoofing target on 2026-09-22 (end of
        # support Oct 2025), so the drawn base IS Windows 11 and already carries
        # the Win11-only families. A native identity is different: camoufox may
        # be RUNNING on a Windows 10 host, and that host cannot render them, so
        # they are removed when the host lacks them rather than added when it
        # has them.
        if variant and not _host_has_variant_fonts(target_os):
            absent = set(variant_fonts)
            result = [f for f in result if f not in absent]
        return result

    # One machine runs one OS version, and has that version's default font set
    # in full -- so the base is drawn whole, by weight, and never subsetted.
    base = _pick_base(os_key, rng)
    if not base:
        # No generated base data: fall back to the always-present core so a
        # draw is still coherent rather than empty.
        base = [f for f in full_list if f in essential]
    result = list(base)
    chosen = set(result)

    # _ESSENTIAL_FONTS_* is the guaranteed floor underneath whichever base was
    # drawn: the GDI-substitution names on Windows and the alias names fonts.conf
    # rewrites unconditionally have no file of their own, so they render for
    # every identity and must be reported by every identity.
    for font in full_list:
        if font in essential and font not in chosen:
            result.append(font)
            chosen.add(font)

    # Everything else is an addition, and each unit is judged on its own
    # real-world probability rather than by a flat sample: Office lands on ~60%
    # of Windows machines, the Pan-European pack on ~2.8%, msttcorefonts on
    # ~13.9% of Linux ones (all measured against the fpgen corpus). Units are
    # atomic, so a draw never produces a partial group -- a partial group is a
    # synthetic artifact no real machine shows (sundial "co-shipped families
    # not split").
    for font in _draw_units(os_key, rng, exclude=chosen, locale=locale):
        if font not in chosen:
            result.append(font)
            chosen.add(font)

    # Ensure marker fonts are present
    _ensure_marker_fonts(result, markers)

    return result


# Essential speech voices per OS that must always be included in subsets
_ESSENTIAL_VOICES_MACOS = [
    'Samantha', 'Alex', 'Fred', 'Victoria', 'Karen', 'Daniel',
]
_ESSENTIAL_VOICES_WINDOWS = [
    'Microsoft David - English (United States)',
    'Microsoft Zira - English (United States)',
    'Microsoft Mark - English (United States)',
]

# Real Firefox speechSynthesis URI prefixes per backend.
#   macOS NSSpeechSynthesizer -> "urn:moz-tts:osx:<dotted-slug>"
#   Windows SAPI              -> "urn:moz-tts:sapi:<dotted-slug>"
#   Linux speech-dispatcher   -> "urn:moz-tts:speechd:<escaped-name>?<lang>"
_VOICE_URI_PREFIX = {
    'mac': 'urn:moz-tts:osx:',
    'win': 'urn:moz-tts:sapi:',
    'lin': 'urn:moz-tts:speechd:',
}


def _voice_uri_slug(name: str) -> str:
    """Stable dotted slug for mac/win URIs (shape-plausible, not catalog-exact)."""
    return re.sub(r'^\.|\.$', '', re.sub(r'[^a-z0-9]+', '.', name.lower()))


def _voice_uri(os_key: str, name: str, lang: str) -> str:
    """Build a voiceUri matching what real Firefox emits for the OS backend."""
    if os_key == 'lin':
        # Firefox's SpeechDispatcherService.cpp builds:
        #   "urn:moz-tts:speechd:" + NS_EscapeURL(name, OnlyNonASCII|Spaces) + "?" + lang
        # i.e. spaces -> %20 and non-ASCII bytes -> %XX, ASCII punctuation intact.
        escaped = []
        for ch in name:
            if ch == ' ':
                escaped.append('%20')
            elif ord(ch) <= 0x7F:
                escaped.append(ch)
            else:
                escaped.append(''.join(f'%{b:02X}' for b in ch.encode('utf-8')))
        return f"{_VOICE_URI_PREFIX['lin']}{''.join(escaped)}?{lang}"
    if os_key == 'win':
        # SapiService.cpp: "urn:moz-tts:sapi:" + name + "?" + lang, verbatim
        # (measured 2026-09-14 on a stock Windows 11: spaces and parentheses
        # unescaped, e.g. "...sapi:Microsoft David - English (United States)?en-US").
        return f"{_VOICE_URI_PREFIX['win']}{name}?{lang}"
    if os_key == 'mac':
        # OSXSpeechSynthesizerService: "urn:moz-tts:osx:" + AVSpeechSynthesisVoice
        # identifier. Catalogue captured from a stock macOS (voice-uris.json);
        # voices outside it follow Apple's identifier families.
        uri = _load_voice_uris().get('mac', {}).get(f'{name}|{lang}')
        if uri:
            return uri
        ascii_name = re.sub(r'[^A-Za-z0-9]', '', unicodedata.normalize('NFKD', name))
        if name in _MAC_NOVELTY_VOICES:
            # e.g. com.apple.speech.synthesis.voice.Albert / .Fred / .Victoria
            # (capitalised as the voice name; multi-word names are joined)
            return f"{_VOICE_URI_PREFIX['mac']}com.apple.speech.synthesis.voice.{ascii_name}"
        if name in _MAC_ELOQUENCE_VOICES:
            return f"{_VOICE_URI_PREFIX['mac']}com.apple.eloquence.{lang}.{ascii_name}"
        return f"{_VOICE_URI_PREFIX['mac']}com.apple.voice.compact.{lang}.{ascii_name}"
    return f"{_VOICE_URI_PREFIX.get(os_key, '')}{_voice_uri_slug(name)}"


_MAC_NOVELTY_VOICES = frozenset(
    {'Albert', 'Bad News', 'Bahh', 'Bells', 'Boing', 'Bubbles', 'Cellos', 'Wobble', 'Good News', 'Jester',
     'Organ', 'Superstar', 'Trinoids', 'Whisper', 'Zarvox', 'Fred', 'Junior', 'Kathy', 'Ralph',
     'Bruce', 'Vicki', 'Victoria', 'Agnes', 'Princess', 'Hysterical', 'Pipe Organ', 'Deranged',
     # not a novelty voice, but the same MacinTalk identifier family
     'Alex'}
)
_MAC_ELOQUENCE_VOICES = frozenset({'Eddy', 'Flo', 'Grandma', 'Grandpa', 'Reed', 'Rocko', 'Sandy', 'Shelley'})
_VOICE_URIS_CACHE: Optional[Dict[str, Dict[str, str]]] = None


def _load_voice_uris() -> Dict[str, Dict[str, str]]:
    """Real voiceURI per "Name|lang" as a stock browser reports it (voice-uris.json)."""
    global _VOICE_URIS_CACHE
    if _VOICE_URIS_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), 'voice-uris.json')
        try:
            with open(path, 'rb') as f:
                _VOICE_URIS_CACHE = json.loads(f.read())
        except OSError:
            _VOICE_URIS_CACHE = {}
    return _VOICE_URIS_CACHE


def _load_voice_manifests() -> Dict[str, Any]:
    """The per-OS installed-voice model (voice-manifests.json): a base the OS
    always ships, Windows language packs keyed by display locale, and additions
    drawn as atomic bundles / a-la-carte voices / whole language packs."""
    global _VOICE_MANIFESTS_CACHE
    if _VOICE_MANIFESTS_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), 'voice-manifests.json')
        with open(path, 'rb') as f:
            _VOICE_MANIFESTS_CACHE = json.loads(f.read())
    return _VOICE_MANIFESTS_CACHE


_VOICE_MANIFESTS_CACHE: Optional[Dict[str, Any]] = None


def _split_voice_entry(entry: str) -> Tuple[str, str, str]:
    name, lang, vtype = entry.rsplit(':', 2)
    return name, lang, vtype


def _weighted_pick(rng: Random, items: List[Dict[str, Any]], wkey: str = 'w') -> Dict[str, Any]:
    total = sum(float(i.get(wkey, 0)) for i in items)
    r = rng.random() * total
    for i in items:
        r -= float(i.get(wkey, 0))
        if r <= 0:
            return i
    return items[-1]


def _weighted_sample(rng: Random, items: List[Any], k: int, weight) -> List[Any]:
    pool = list(items)
    out: List[Any] = []
    while pool and len(out) < k:
        total = sum(weight(x) for x in pool)
        r = rng.random() * total
        for x in pool:
            r -= weight(x)
            if r <= 0:
                out.append(x)
                pool.remove(x)
                break
        else:
            out.append(pool.pop())
    return out


def _resolve_display_pack(packs: Dict[str, Any], fallback: str, locale: Optional[str]) -> str:
    if locale:
        if locale in packs:
            return locale
        lang = locale.split('-')[0].lower()
        for key in packs:
            if key.split('-')[0].lower() == lang:
                return key
    return fallback if fallback in packs else next(iter(packs))


def _generate_random_voice_subset(
    target_os: str, locale: Optional[str] = None, seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """Generate the speech voice list for the given OS as MaskConfig objects.

    Returns a list of {lang, name, voiceUri, isDefault, isLocalService} dicts,
    the shape MaskConfig::MVoices() requires (it silently drops any entry
    missing a field, so raw name strings would register nothing).

    Without this override, Firefox registers the HOST machine's
    speech-dispatcher / SAPI / NSSpeech voices, leaking the OS the wrapper
    actually runs on. The list follows a measured model of what a stock
    machine exposes (voice-manifests.json):
      Windows: the display language's OneCore pack (en-US: David/Mark/Zira),
               its legacy "Desktop" tokens, and occasionally extra packs;
      macOS:   the compact + Eloquence base (~184 voices) plus rare downloads;
      Linux:   speech-dispatcher's fixed espeak-ng list (131 voices).
    Seeded by the identity so the same identity always reports the same list.
    """
    rng = _rng(seed)
    os_key = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}.get(target_os, 'mac')
    manifest = _load_voice_manifests().get(os_key) or _load_voice_manifests()['mac']

    out: List[str] = []
    seen = set()

    def add(entries):
        for e in entries or []:
            if e not in seen:
                seen.add(e)
                out.append(e)

    legacy: List[str] = []
    packs = manifest.get('langPacks') or {}

    def take_pack(pack):
        add(pack.get('oneCore'))
        if pack.get('desktop') and rng.random() < float(pack.get('desktopProb') or 0):
            for e in pack['desktop']:
                if e not in legacy:
                    legacy.append(e)

    add(manifest.get('base'))
    chosen = set()
    if packs:
        key = _resolve_display_pack(packs, manifest.get('fallbackLocale') or 'en-US', locale)
        chosen.add(key)
        take_pack(packs[key])

    for addition in manifest.get('additions', []):
        if addition.get('deferred'):
            continue
        req = addition.get('requiresLocale')
        if req and not (locale or '').lower().startswith(req.lower()):
            continue
        if rng.random() >= float(addition.get('prob') or 0):
            continue
        kind = addition.get('kind')
        if kind == 'bundle':
            add(addition.get('voices'))
        elif kind == 'alacarte':
            sizes = addition.get('sizes') or [{'n': 1, 'w': 1}]
            k = int(_weighted_pick(rng, sizes)['n'])
            for e in _weighted_sample(rng, addition.get('voices') or [], k, lambda x: 1.0):
                if e not in seen:
                    seen.add(e)
                    # a downloaded voice sits in its alphabetical place
                    idx = next((i for i, v in enumerate(out) if v.lower() > e.lower()), len(out))
                    out.insert(idx, e)
        elif kind == 'groups' and packs:
            eligible = [g for g in addition.get('groups') or [] if g in packs and g not in chosen]
            if not eligible:
                continue
            k = int(_weighted_pick(rng, addition['sizes'])['n']) if addition.get('sizes') else len(eligible)
            for g in _weighted_sample(rng, eligible, k, lambda g: float(packs[g].get('weight') or 0.01)):
                chosen.add(g)
                take_pack(packs[g])

    selected = [_split_voice_entry(e) for e in out + legacy]
    if not selected:
        return []

    voices: List[Dict[str, Any]] = [
        {
            'name': name,
            'lang': lang,
            'voiceUri': _voice_uri(os_key, name, lang),
            'isDefault': False,
            'isLocalService': vtype == 'local',
        }
        for (name, lang, vtype) in selected
    ]

    # No voice carries default=true: stock Firefox 152 marks none on Windows
    # (SAPI), macOS or Linux (measured 2026-09-14 on all three), so a spoofed
    # default would be the odd one out.
    return voices


def _normalize_preset_voices(
    voices: Any, target_os: str
) -> List[Dict[str, Any]]:
    """Coerce a preset's `speechVoices` into MaskConfig voice objects.

    Presets historically store voices as "Name:lang:type" strings, which the
    C++ MaskConfig::MVoices() silently drops (it needs full objects). Convert
    them; pass through entries that are already objects.
    """
    os_key = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}.get(target_os, 'mac')
    result: List[Dict[str, Any]] = []
    for entry in voices:
        if isinstance(entry, dict):
            result.append(entry)
            continue
        last = entry.rfind(':')
        if last < 0:
            continue
        vtype = entry[last + 1:]
        before = entry[:last]
        langsep = before.rfind(':')
        if langsep < 0:
            continue
        lang = before[langsep + 1:]
        name = before[:langsep]
        if not name or not lang:
            continue
        result.append(
            {
                'name': name,
                'lang': lang,
                'voiceUri': _voice_uri(os_key, name, lang),
                'isDefault': False,
                'isLocalService': vtype == 'local',
            }
        )
    if result and not any(v['isDefault'] for v in result):
        result[0]['isDefault'] = True
    return result


def host_cpu_count() -> Optional[int]:
    """Logical CPUs this process may actually run on (cgroup/affinity aware)."""
    try:
        return len(os.sched_getaffinity(0)) or None  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return os.cpu_count()


# Core counts real desktop machines ship with, taken from the RECORDED
# fingerprint corpus rather than invented: fingerprint-presets.json and
# -v150.json between them contain 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24,
# 28 and 32 (18: macOS 2/67; 22: Windows 6/180, Linux 2/65; 28: Windows 2/180,
# Linux 1/65; 32: Linux 1/65 -- all in -v150). Leaving any of them out snapped
# genuine machines with that count down to the next entry for no reason.
#
# 2 is EXCLUDED, and stays excluded -- but not for the reason first written
# here. That reason ("2 is what Firefox reports under resistFingerprinting") is
# false and has been for years: RuntimeService::ClampedHardwareConcurrency
# (dom/workers/RuntimeService.cpp, read in the 152 tree on 2026-09-17) hardcodes
# 4 under RFP, and 8 on macOS -- both already in this table.
#
# The real reason is coherence with the rest of the identity. 85% of macOS
# identities draw "Apple M1, or similar" as the WebGL renderer, and no Apple
# Silicon part has ever had 2 cores; the lowest is 8. A page reading
# navigator.hardwareConcurrency and UNMASKED_RENDERER_WEBGL together -- two
# property reads -- would see a machine that does not exist.
#
# The recorded corpus does contain 2 (11/67 macOS presets, 17/180 Windows,
# 6/65 Linux), and that is not a reason to ship it: those rows report 2 more
# often than 4 on macOS, which no real hardware population does. The corpus is
# scraped from live traffic, so it carries other people's privacy-hardened
# browsers, 2-vCPU VMs and bots. "The corpus says so" settles what real MACHINES
# report only where the field is hardware; this one is a number the browser can
# be made to say.
#
# A host outside this table would hand its own oddity to the fingerprint: a
# 64-thread build box reports 32, anything under 4 threads reports 4. Odd
# counts (5, 7, 9, 11, 13, 15) never appear in the corpus -- they are
# browserforge Bayesian synthesis -- so they keep getting snapped down.
PLAUSIBLE_CORE_COUNTS = (4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 32)


def fix_hardware_concurrency(config: Dict[str, Any], can_pin: Optional[bool] = None) -> None:
    """navigator.hardwareConcurrency = the host's parallelism, snapped DOWN
    into PLAUSIBLE_CORE_COUNTS.

    A drawn value that differs from the machine the browser runs on is
    measurable from a page: timing N parallel workers reveals how many cores
    are really usable, and both "more usable than reported" and "fewer usable
    than reported" are flagged by WebCPU-style checks (sundial "CPU: reported
    vs measured cores"; daijro/camoufox#442 for the drift across launches).
    So the drawn value is discarded, not clamped: min(drawn, host) still lets
    a draw of 2 be measured as 16.

    Stock Firefox 152 reports the true count in a normal window (capped by
    dom.maxHardwareConcurrency = 128; measured 2026-09-14: 16-thread Linux and
    Windows hosts -> 16, a 10-core Mac mini -> 10). Its 8/4 tiering
    (RFPTarget NavigatorHWConcurrencyTiered: >= 8 -> 8, else 4) applies only
    with fingerprinting protection on, i.e. private windows and ETP strict,
    and resistFingerprinting hardcodes 4 (8 on macOS) -- neither is a normal
    window's behaviour, so nothing is rounded here beyond the table snap.
    The two tails (host > 20 or < 4) are the residual where reported and
    measurable can disagree; closing them needs CPU affinity pinning, not a
    launcher value. A caller that sets navigator.hardwareConcurrency
    themselves is left alone (see the _user_set_navigator guard).
    """
    n = host_cpu_count()
    if not n:
        return
    # The fingerprint's own value survives when the browser can be pinned to
    # that many cores (cpu_affinity: Linux, Windows): reported and measurable
    # then agree by construction, and the identity keeps its diversity. A draw
    # the host cannot honour (more cores than it has), a host that cannot pin
    # (macOS), or pin_cpu_cores left off -- the default since 2026-09-17 --
    # falls back to the snapped host count, which is equally coherent.
    from .cpu_affinity import supported as _can_pin

    # can_pin=False: the caller launches the browser itself and nothing will
    # pin it (launch_server, launch_options used directly), so a kept draw
    # would be measured as the host count. None: whatever the host supports.
    pinnable = _can_pin() and can_pin is not False

    cap = int(n)
    host_allowed = [c for c in PLAUSIBLE_CORE_COUNTS if c <= cap]
    host_value = host_allowed[-1] if host_allowed else PLAUSIBLE_CORE_COUNTS[0]

    drawn = config.get('navigator.hardwareConcurrency')
    if pinnable and isinstance(drawn, int) and drawn >= 1:
        # The fingerprint's value is kept for diversity, but it still has to be
        # a count a real desktop ships with. Accepting any 1..host let
        # browserforge's synthetic odd draws through (5, 7, 9, 11, 13, 15 --
        # counts the corpus never records). Snap the draw DOWN into the table
        # instead, capped by the host so pinning can honour it.
        target = min(drawn, cap)
        allowed = [c for c in PLAUSIBLE_CORE_COUNTS if c <= target]
        # The floor is the table's even on a 1-3 core host: reporting the host's
        # own 1, 2 or 3 would contradict the drawn GPU (see the table above).
        config['navigator.hardwareConcurrency'] = (
            allowed[-1] if allowed else PLAUSIBLE_CORE_COUNTS[0]
        )
        return
    config['navigator.hardwareConcurrency'] = host_value


def fix_navigator_arch(config: Dict[str, Any], target_os: str) -> None:
    """Force navigator.platform AND navigator.oscpu to match the UA's arch.

    ~8% of Linux Firefox fingerprints in the BrowserForge pool report
    "Linux armv81" for platform/oscpu while the UA says "Linux x86_64". That
    arch mismatch is itself a CreepJS lie signal (CreepJS cross-checks oscpu,
    platform, and the UA arch). Mac/Windows pools are consistent and need no
    correction.
    """
    if target_os != 'lin':
        return
    ua = config.get('navigator.userAgent')
    if not ua:
        return
    target = ''
    if 'Linux x86_64' in ua:
        target = 'Linux x86_64'
    elif 'Linux i686' in ua:
        target = 'Linux i686'
    if not target:
        return
    if config.get('navigator.platform') != target:
        config['navigator.platform'] = target
    if config.get('navigator.oscpu') != target:
        config['navigator.oscpu'] = target


def fix_screen_no_taskbar(config: Dict[str, Any], target_os: str) -> None:
    """Ensure screen.availHeight < screen.height so CreepJS's noTaskbar flag
    (screen.height == availHeight and screen.width == availWidth) doesn't flip.

    Every desktop OS keeps some chrome visible (Mac menu bar ~25px, Win taskbar
    ~40px, Linux panel ~27px); the pool occasionally ships fingerprints with
    identical screen/avail values which leak as a headless tell. Also clamp
    window.outerHeight (and innerHeight) to the new avail so the window isn't
    taller than the available area.

    The trigger is the HEIGHT alone, not both axes. Requiring `aw == sw` too
    missed the shape `availWidth < width, availHeight == height` -- a Windows
    taskbar docked left or right. That is a real geometry, but a rare one, and
    letting it through means claiming no vertical chrome at all: no menu bar on
    a Mac, no bottom taskbar on Windows, no panel on Linux. Those defaults are
    overwhelmingly more common than a side dock, so the vertical delta is worth
    more than the handful of genuine side-docked machines it overwrites. fpgen's
    2026 model surfaced this: conditioned on a small display it produced that
    shape in ~30% of draws, where the unconditioned rate is under 1%.
    """
    sw = config.get('screen.width')
    sh = config.get('screen.height')
    ah = config.get('screen.availHeight')
    if not (sw and sh and ah == sh):
        return
    taskbar = 40 if target_os == 'win' else 25 if target_os == 'mac' else 27
    new_avail = sh - taskbar
    config['screen.availHeight'] = new_avail
    oh = config.get('window.outerHeight')
    if oh and oh > new_avail:
        ih = config.get('window.innerHeight')
        chrome = oh - ih if ih else 0
        config['window.outerHeight'] = new_avail
        if ih:
            config['window.innerHeight'] = new_avail - chrome


def clamp_window_dimensions(config: Dict[str, Any]) -> None:
    """Enforce inner <= outer <= avail <= screen on BOTH axes.

    The browser faithfully reports whatever we inject, so a BrowserForge
    fingerprint that ships e.g. outerWidth > screen.width or innerWidth >
    outerWidth leaks as an impossible geometry. Shrink each level down to its
    container, preserving the chrome delta between outer and inner where
    possible. Complements fix_screen_no_taskbar (which only clamps height).
    """
    for axis in ('Width', 'Height'):
        screen = config.get(f'screen.{axis.lower()}')
        avail = config.get(f'screen.avail{axis}')
        outer = config.get(f'window.outer{axis}')
        inner = config.get(f'window.inner{axis}')

        # avail must not exceed screen
        if screen and avail and avail > screen:
            config[f'screen.avail{axis}'] = screen
        avail_clamped = config.get(f'screen.avail{axis}', screen)

        # outer must not exceed avail (or screen if avail is unknown)
        outer_cap = avail_clamped if avail_clamped is not None else screen
        if outer and outer_cap and outer > outer_cap:
            chrome = max(0, outer - inner) if inner else 0
            config[f'window.outer{axis}'] = outer_cap
            if inner:
                config[f'window.inner{axis}'] = max(1, outer_cap - chrome)

        # inner must not exceed outer
        outer_clamped = config.get(f'window.outer{axis}', outer)
        inner_now = config.get(f'window.inner{axis}')
        if inner_now and outer_clamped and inner_now > outer_clamped:
            config[f'window.inner{axis}'] = outer_clamped


def clamp_screen_to_display(
    config: Dict[str, Any],
    max_width: Optional[int],
    max_height: Optional[int],
) -> None:
    """Shrink screen.width/height down to the bounds of the real display.

    BrowserForge takes a Screen constraint but drops it silently whenever it
    filters the fingerprint pool too far: FingerprintGenerator.partial_csp
    swallows the resulting failure and deletes the constraint unless strict=True.
    So the bound from get_screen_cons() is best-effort only, and a 1366x768
    laptop routinely gets a 2560x1440 fingerprint. browser-init.patch resizes the
    real chrome window to window.outerWidth/outerHeight, so an unbounded value
    renders past the edge of the monitor (daijro/camoufox#499).

    Keeps the taskbar delta (screen - avail) intact so fix_screen_no_taskbar's
    invariant survives. Callers must run clamp_window_dimensions afterwards to
    cascade the new bounds down to avail/outer/inner.
    """
    for axis, cap in (('width', max_width), ('height', max_height)):
        screen = config.get(f'screen.{axis}')
        if not (screen and cap) or screen <= cap:
            continue
        avail_key = 'screen.availWidth' if axis == 'width' else 'screen.availHeight'
        avail = config.get(avail_key)
        config[f'screen.{axis}'] = cap
        if avail:
            config[avail_key] = max(1, cap - max(0, screen - avail))


def clamp_window_position(config: Dict[str, Any]) -> None:
    """Keep the window box inside the screen: 0 <= screenX/Y <= screen - outer.

    BrowserForge's screenX/screenY are consistent with the screen it generated
    them against, so clamp_screen_to_display invalidates them. A window
    positioned partly off its own reported screen is an impossible geometry.
    """
    for axis, pos_key in (('Width', 'window.screenX'), ('Height', 'window.screenY')):
        screen = config.get(f'screen.{axis.lower()}')
        outer = config.get(f'window.outer{axis}')
        pos = config.get(pos_key)
        if pos is None or not (screen and outer):
            continue
        config[pos_key] = max(0, min(pos, screen - outer))


def set_media_devices_defaults(config: Dict[str, Any], salt: int = 0) -> None:
    """Give the identity a plausible set of media devices.

    The patched media backend (media-device-spoofing.patch) enumerates and
    captures exactly the devices described by mediaDevices:{enabled, micros,
    webcams, speakers} and the aligned mediaDevices:{microphone,webcam,
    speaker}{Labels,Groups} lists, and Firefox's own pre-/post-grant exposure
    rules apply to them. Nothing is drawn when the caller already set any
    mediaDevices: key.
    """
    if any(k.startswith('mediaDevices:') for k in config):
        return
    # Before any getUserMedia grant Firefox exposes at most ONE device per
    # input kind and no audiooutput; after a grant it lists every device with
    # the OS's own labels ("Microphone Array (Realtek(R) Audio)", "MacBook Pro
    # Microphone", "Built-in Audio Analog Stereo"...). Draw a whole machine's
    # worth from the common desktop population for the claimed OS
    # (media-devices.json), seeded by the identity so the same identity
    # always reports the same devices. The browser applies the stock
    # pre-/post-grant exposure rules to this list.
    plat = str(config.get('navigator.platform', ''))
    if plat.startswith('Win'):
        os_key = 'win'
    elif plat.startswith('Mac'):
        os_key = 'mac'
    else:
        os_key = 'lin'
    config.update(draw_media_devices(os_key, identity_seed(config, salt)))


_MEDIA_DEVICES_CACHE: Optional[Dict[str, Any]] = None


def _load_media_devices() -> Dict[str, Any]:
    """Per-OS catalogue of common sound cards / headsets / display audio /
    cameras with their post-grant labels (media-devices.json)."""
    global _MEDIA_DEVICES_CACHE
    if _MEDIA_DEVICES_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), 'media-devices.json')
        with open(path, 'rb') as f:
            _MEDIA_DEVICES_CACHE = json.loads(f.read())
    return _MEDIA_DEVICES_CACHE


def _weighted_choice(rng: Random, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = float(sum(item.get('w', 1) for item in items))
    r = rng.random() * total
    for item in items:
        r -= item.get('w', 1)
        if r < 0:
            return item
    return items[-1]


# Share of machines with no microphone at all (a desktop tower with only a
# line-out) and with a built-in camera, per OS. macOS is modelled by the
# machine line itself (Mac mini / Mac Studio have neither).
_MEDIA_P_NO_MIC = {'win': 0.08, 'mac': 0.0, 'lin': 0.20}
_MEDIA_P_BUILTIN_CAM = {'win': 0.78, 'mac': 0.0, 'lin': 0.45}


def draw_media_devices(os_key: str, seed: Optional[int]) -> Dict[str, Any]:
    """Draw one machine's media devices for `os_key` ('win'|'mac'|'lin').

    Returns the mediaDevices:* config keys: counts plus aligned label and
    group lists. Devices of one piece of hardware (a sound card's microphone
    and speakers, a webcam and its microphone) share a group, as their
    groupId does on a real machine; Linux additionally lists the PulseAudio
    "Monitor of ..." source of every output as a microphone, as Firefox does.
    """
    rng = _rng(seed)
    cat = _load_media_devices().get(os_key) or _load_media_devices()['win']
    mics: List[Tuple[str, str]] = []
    outs: List[Tuple[str, str]] = []
    cams: List[Tuple[str, str]] = []
    counter = [0]

    def group() -> str:
        counter[0] += 1
        return f'hw-{counter[0]}'

    def add(item: Dict[str, Any], grp: str) -> None:
        for m in item.get('mics', []):
            mics.append((m, grp))
        for o in item.get('outs', []):
            outs.append((o, grp))
        if item.get('cam'):
            cams.append((item['cam'], group()))

    # 1. the machine's own sound card (+ built-in camera on macOS models)
    card = _weighted_choice(rng, cat['cards'])
    no_mic = rng.random() < _MEDIA_P_NO_MIC.get(os_key, 0.0)
    card_grp = group()
    if no_mic:
        add({**card, 'mics': []}, card_grp)
    else:
        add(card, card_grp)
    # 2. a built-in laptop camera (Windows/Linux); rare on a mic-less tower
    p_cam = _MEDIA_P_BUILTIN_CAM.get(os_key, 0.0)
    if rng.random() < (p_cam * 0.3 if no_mic else p_cam):
        builtin = [c for c in cat['cameras'] if not c.get('mic')]
        if builtin:
            cams.append((_weighted_choice(rng, builtin)['cam'], group()))
    # 3. a headset / USB microphone
    if rng.random() < cat.get('p_headset', 0.0):
        add(_weighted_choice(rng, cat['headsets']), group())
    # 4. display audio (HDMI/DP) -- occasionally a display with mic + camera
    if rng.random() < cat.get('p_display', 0.0):
        add(_weighted_choice(rng, cat['displays']), group())
    # 5. an external webcam, usually with its own microphone
    if rng.random() < cat.get('p_extra_camera', 0.0):
        external = [c for c in cat['cameras'] if c.get('mic')] or cat['cameras']
        cam = _weighted_choice(rng, external)
        grp = group()
        cams.append((cam['cam'], grp))
        if cam.get('mic'):
            mics.append((cam['mic'], grp))
    # 6. PulseAudio exposes a monitor source per output as a capture device
    if cat.get('monitor_sources'):
        for label, grp in list(outs):
            mics.append((f'Monitor of {label}', grp))

    return {
        'mediaDevices:enabled': True,
        'mediaDevices:micros': len(mics),
        'mediaDevices:webcams': len(cams),
        'mediaDevices:speakers': len(outs),
        'mediaDevices:microphoneLabels': [m for m, _ in mics],
        'mediaDevices:microphoneGroups': [g for _, g in mics],
        'mediaDevices:webcamLabels': [c for c, _ in cams],
        'mediaDevices:webcamGroups': [g for _, g in cams],
        'mediaDevices:speakerLabels': [o for o, _ in outs],
        'mediaDevices:speakerGroups': [g for _, g in outs],
    }


# -- WebGL <-> screen coherence (#729) ---------------------------------------
#
# fpgen picks navigator/screen; the GPU is drawn separately, weighted only by
# OS (camoufox.webgl). Nothing ties the two together, so the
# synthetic path can emit pairs no real machine ships -- a discrete GPU behind
# a 1024x600 netbook panel. Consistency checks (Pixelscan, Fingerprint.com)
# read that as masking even when every individual value is plausible alone.
#
# What can honestly be claimed here is narrow, because Firefox never reports
# the GPU it actually sees. dom/canvas/SanitizeRenderer.cpp collapses every
# renderer string into one of ~11 representative device buckets before a page
# sees it (prefs webgl.sanitize-unmasked-renderer and
# webgl.enable-renderer-query, both default true; resistFingerprinting
# replaces the value with "Mozilla" outright). That file's own header comment
# gives the flavour: `"GeForce RTX 3090" => "GeForce GTX 980"`. So every RTX,
# every Quadro M/P/V/T and every GeForce 900-7999 arrive as one string, while
# "Intel(R) UHD Graphics 620" and "Mesa Intel(R) Iris(R) Xe Graphics" both
# arrive as an "Intel(R) HD Graphics" spelling.
#
# Two consequences. Matching on raw model names -- RTX, Quadro, RX, UHD, Iris,
# Mesa Intel -- can never fire, because those are exactly the strings Gecko
# collapses away. And a bucket spanning a desktop RTX 4090 and a mobile GTX
# 1650 Max-Q carries no useful screen floor: 1366x768 laptops with discrete
# NVIDIA GPUs are ordinary hardware, not a tell.
#
# So the rule below holds only what is true of *every* part behind a bucket,
# and renderers are reduced to their bucket first (see _renderer_bucket) so
# the ANGLE, nouveau and /PCIe/SSE2 spellings of one GPU land on one rule
# instead of three different ones.

# Software rasterizers. A VM or headless host reports whatever resolution the
# window manager hands it, so no screen constrains them -- and the sampler
# must never come to *prefer* them, because a software renderer is a far
# stronger "this is a bot" signal than any GPU/screen mismatch.
_SOFTWARE_RENDERERS: Tuple[str, ...] = (
    'llvmpipe',
    'Microsoft Basic Render Driver',
    'SwiftShader',
    'Generic Renderer',
)

# Discrete NVIDIA, plus the AMD R5/R7/R9/RX/Vega bucket. Every other GPU
# Firefox reports reaches down into netbook territory and gets no floor at all:
# the "Intel(R) HD Graphics" bucket swallows the GMA 3150 netbook chipset,
# "Radeon HD 3200 Graphics" is Gecko's catch-all for a bare "AMD"/"Radeon"
# (the C-50/E-350 netbook APUs included), and Apple silicon drives arbitrary
# external monitors from a Mac mini or Mac Studio.
_DISCRETE_GPU_BUCKETS: FrozenSet[str] = frozenset(
    {
        'GeForce 8800 GTX',
        'GeForce GTX 480',
        'GeForce GTX 980',
        'Radeon R9 200 Series',
    }
)

# Discrete GPUs did not ship in netbooks, and netbook panels topped out at
# 1024x600. That is the whole of the claim.
#
# It is an area rather than a width x height pair because real panels do not
# dominate one another: 1280x800 and 1366x768 are both ordinary laptop
# screens, and a per-axis floor taken from either one rejects the other. A
# 1366x768 laptop with a discrete GPU is common hardware, not a tell.
_NETBOOK_MAX_PIXELS = 1024 * 600

# The three shapes SanitizeRenderer wraps a device bucket in.
_ANGLE_D3D_RE = re.compile(r'^ANGLE \([^,]*, (.*?) Direct3D.*\)$')
_ANGLE_VULKAN_RE = re.compile(r'^ANGLE \((.*)\) on Vulkan$')
_PCIE_SSE2_RE = re.compile(r'^(.*)/PCIe?/SSE2$')


def _renderer_bucket(renderer: str) -> str:
    """Reduce a reported renderer to Gecko's sanitized device bucket.

    "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or
    similar" (Windows), "NVIDIA GeForce GTX 980/PCIe/SSE2" (Linux proprietary
    driver) and "GeForce GTX 980, or similar" (nouveau, which loses the vendor
    prefix) are one GPU class in three spellings. Without this they land on
    three different rules, or none.
    """
    core = renderer.removesuffix(', or similar')
    match = _ANGLE_D3D_RE.match(core) or _ANGLE_VULKAN_RE.match(core)
    if match:
        core = match.group(1)
    match = _PCIE_SSE2_RE.match(core)
    if match:
        core = match.group(1)
    # SanitizeRenderer re-adds the "NVIDIA " prefix only when the raw string
    # carried it, so one bucket arrives both with and without it.
    return core.removeprefix('NVIDIA ')


# The smallest screen mainstream hardware still ships. BrowserForge's pool
# carries netbook-era geometry that essentially no 2026 device reports, and
# that is a tell on its own, whatever GPU sits behind it.
MODERN_SCREEN_FLOOR: Tuple[int, int] = (1366, 768)


def raise_screen_to_modern_floor(config: Dict[str, Any]) -> None:
    """Lift netbook-era screen geometry to something current hardware reports.

    BrowserForge still draws 1024x600 and friends. Those panels left
    production a decade and a half ago, so the screen is what has to move --
    no GPU choice makes that profile look current.

    Keeps the screen-to-avail gap intact so fix_screen_no_taskbar's invariant
    survives; the window box is reconciled by clamp_window_dimensions and
    clamp_window_position, which run after this. Call BEFORE
    clamp_screen_to_display so a genuinely small real monitor still wins.
    """
    min_w, min_h = MODERN_SCREEN_FLOOR
    sw = config.get('screen.width')
    sh = config.get('screen.height')
    if not (sw and sh) or (sw >= min_w and sh >= min_h):
        return

    # Measure the gaps before mutating, or they get folded into themselves.
    aw = config.get('screen.availWidth')
    ah = config.get('screen.availHeight')
    gap_w = sw - aw if aw else None
    gap_h = sh - ah if ah else None

    new_w, new_h = max(sw, min_w), max(sh, min_h)
    config['screen.width'] = new_w
    config['screen.height'] = new_h
    if gap_w is not None:
        config['screen.availWidth'] = max(1, new_w - max(0, gap_w))
    if gap_h is not None:
        config['screen.availHeight'] = max(1, new_h - max(0, gap_h))


def is_software_renderer(renderer: Optional[str]) -> bool:
    """Whether `renderer` is a software rasterizer rather than real hardware."""
    return bool(renderer) and any(name in renderer for name in _SOFTWARE_RENDERERS)


def gpu_screen_is_plausible(
    renderer: Optional[str], width: Optional[int], height: Optional[int]
) -> bool:
    """Whether `renderer` is a GPU that plausibly drives a `width` x `height` screen.

    Unconstrained buckets and software rasterizers pass. The set only names
    buckets whose floor holds for every part behind them, so anything absent
    from it is genuinely unconstrained rather than merely unrecognised.
    """
    if not renderer or not width or not height:
        return True
    if is_software_renderer(renderer):
        return True
    if _renderer_bucket(renderer) not in _DISCRETE_GPU_BUCKETS:
        return True
    return width * height > _NETBOOK_MAX_PIXELS


def _select_presets_file(ff_version: Optional[Any] = None) -> Path:
    """Pick the bundled-presets file appropriate for a given Firefox version.

    For Firefox >= PRESETS_V150_MIN_FF, prefer the v150 bundle (real
    fingerprints scraped from contemporary browsers); otherwise fall back to
    the original bundle.
    """
    try:
        major = int(str(ff_version).split('.', 1)[0]) if ff_version else 0
    except (ValueError, TypeError):
        major = 0
    if major >= PRESETS_V150_MIN_FF and PRESETS_V150_FILE.exists():
        return PRESETS_V150_FILE
    return PRESETS_FILE


def load_presets(ff_version: Optional[Any] = None) -> Optional[Dict]:
    """Load bundled fingerprint presets from JSON file."""
    path = _select_presets_file(ff_version)
    if path in _PRESETS_CACHE:
        return _PRESETS_CACHE[path]
    if not path.exists():
        return None
    with open(path) as f:
        _PRESETS_CACHE[path] = json.load(f)
    return _PRESETS_CACHE[path]


# Map OS names to preset keys
_OS_TO_PRESET_KEY = {
    'windows': 'windows',
    'macos': 'macos',
    'linux': 'linux',
    'win': 'windows',
    'mac': 'macos',
    'lin': 'linux',
}


def get_random_preset(
    os: Optional[str] = None,
    ff_version: Optional[Any] = None,
) -> Optional[Dict]:
    """
    Get a random preset for the given OS.
    Returns None if no presets are available.
    """
    presets = load_presets(ff_version)
    if not presets:
        return None

    all_os_keys = ['macos', 'windows', 'linux']

    if os:
        # Normalize OS name
        if isinstance(os, (list, tuple)):
            os_keys = [_OS_TO_PRESET_KEY.get(o, o) for o in os]
        else:
            os_keys = [_OS_TO_PRESET_KEY.get(os, os)]
    else:
        os_keys = all_os_keys

    # Collect all matching presets
    candidates: List[Dict] = []
    for key in os_keys:
        candidates.extend(presets.get('presets', {}).get(key, []))

    if not candidates:
        return None

    return choice(candidates)  # nosec


# Tokens that name the machine rather than the platform: Firefox leaves every one
# of them out of appVersion.
_APP_VERSION_DROPPED = ('Win64', 'x64', 'Mobile', 'Tablet')


def _app_version_from_user_agent(user_agent: str) -> Optional[str]:
    """The appVersion Firefox reports for a browser sending this user agent.

    "5.0 (<OS tokens>)": the parenthesised part of the UA without the
    architecture, the Gecko revision, or the Windows build number.
    """
    block = re.match(r'Mozilla/5\.0 \(([^)]*)\)', user_agent or '')
    if not block:
        return None
    kept = []
    for token in (part.strip() for part in block.group(1).split(';')):
        if (
            token.startswith('rv:')
            or token in _APP_VERSION_DROPPED
            or token.startswith('Linux ')
            or token.startswith('Intel Mac OS X')
        ):
            continue
        kept.append('Windows' if token.startswith('Windows') else token)
    return f"5.0 ({'; '.join(kept)})" if kept else None


def from_preset(preset: Dict, ff_version: Optional[str] = None, salt: Optional[int] = None) -> Dict[str, Any]:
    """
    Convert a real fingerprint preset to CAMOU_CONFIG format.

    `salt` (identity_salt) keys the font/voice draws; None draws a fresh one, so
    two users of the same recorded device do not also share its font list.
    """
    if salt is None:
        salt = identity_salt()
    config: Dict[str, Any] = {}

    nav = preset.get('navigator', {})
    if nav.get('userAgent'):
        ua = nav['userAgent']
        # Replace Firefox version in UA if ff_version is provided
        if ff_version:
            ua = re.sub(r'Firefox/\d+\.0', f'Firefox/{ff_version}.0', ua)
            ua = re.sub(r'rv:\d+\.0', f'rv:{ff_version}.0', ua)
        config['navigator.userAgent'] = ua
    if nav.get('platform'):
        config['navigator.platform'] = nav['platform']
    if nav.get('hardwareConcurrency'):
        config['navigator.hardwareConcurrency'] = nav['hardwareConcurrency']
    if nav.get('oscpu'):
        config['navigator.oscpu'] = nav['oscpu']
    elif nav.get('platform'):
        # Derive oscpu from platform when not explicitly in the preset
        plat = nav['platform']
        if plat == 'MacIntel':
            config['navigator.oscpu'] = 'Intel Mac OS X 10.15'
        elif plat == 'Win32':
            config['navigator.oscpu'] = 'Windows NT 10.0; Win64; x64'
        elif 'Linux' in plat or 'linux' in plat:
            config['navigator.oscpu'] = 'Linux x86_64'
    if nav.get('appVersion'):
        config['navigator.appVersion'] = nav['appVersion']
    elif config.get('navigator.userAgent'):
        # Left unset, appVersion falls through to the *host's* value and then
        # contradicts the userAgent and platform set above: a Linux preset on a
        # macOS host reported "5.0 (Macintosh)" beside platform "Linux x86_64",
        # which any page can read in two properties.
        #
        # Firefox builds it from the same OS tokens as the userAgent, minus the
        # architecture and rv, with Windows collapsed to its family name. Deriving
        # it from the UA rather than from the platform keeps the distro token that
        # 20 of the bundled Linux presets carry ("X11; Ubuntu"), which a platform
        # lookup would flatten to "X11" — a mismatch of the same kind, if a
        # smaller one. Checked against 800 browserforge fingerprints: exact every
        # time.
        derived = _app_version_from_user_agent(config['navigator.userAgent'])
        if derived:
            config['navigator.appVersion'] = derived
    if 'maxTouchPoints' in nav:
        config['navigator.maxTouchPoints'] = nav['maxTouchPoints']

    screen = preset.get('screen', {})
    if screen.get('width'):
        config['screen.width'] = screen['width']
    if screen.get('height'):
        config['screen.height'] = screen['height']
    if screen.get('colorDepth'):
        config['screen.colorDepth'] = screen['colorDepth']
        config['screen.pixelDepth'] = screen['colorDepth']
    if screen.get('availWidth'):
        config['screen.availWidth'] = screen['availWidth']
    if screen.get('availHeight'):
        config['screen.availHeight'] = screen['availHeight']

    webgl = preset.get('webgl', {})
    if webgl.get('unmaskedVendor'):
        config['webGl:vendor'] = webgl['unmaskedVendor']
    if webgl.get('unmaskedRenderer'):
        config['webGl:renderer'] = webgl['unmaskedRenderer']

    # Generate a unique audio seed per launch (1 to 2^32-1, excluding 0 which is a no-op in C++)
    config['audio:seed'] = randint(1, 4_294_967_295)  # nosec

    if preset.get('timezone'):
        config['timezone'] = preset['timezone']

    # Generate a unique random font subset from the OS font list.
    plat = nav.get('platform', '')
    if plat == 'MacIntel':
        target_os = 'macos'
    elif plat == 'Win32':
        target_os = 'windows'
    elif 'Linux' in plat or 'linux' in plat:
        target_os = 'linux'
    else:
        target_os = 'macos'
    preset_key = f"{config.get('navigator.userAgent')} / {config.get('webGl:renderer')}"
    try:
        config['fonts'] = _generate_random_font_subset(target_os, seed=identity_seed(config, salt))
    except (OSError, ValueError) as e:
        FallbackWarning.warn(
            'Drawing the font list',
            "the preset's recorded fonts" if preset.get('fonts') else "the browser's own fonts",
            e,
            preset_key,
        )
        if preset.get('fonts'):
            fonts = list(preset['fonts'])
            _ensure_marker_fonts(fonts, {
                'macos': _MACOS_MARKER_FONTS,
                'windows': _WINDOWS_MARKER_FONTS,
                'linux': _LINUX_MARKER_FONTS,
            }.get(target_os, _MACOS_MARKER_FONTS))
            config['fonts'] = fonts
    # Generate a unique random voice subset from the OS voice list
    try:
        config['voices'] = _generate_random_voice_subset(target_os, seed=identity_seed(config, salt))
    except (OSError, ValueError, KeyError) as e:
        FallbackWarning.warn(
            'Drawing the speech voices',
            "the preset's recorded voices" if preset.get('speechVoices') else "the browser's own voices",
            e,
            preset_key,
        )
        if preset.get('speechVoices'):
            config['voices'] = _normalize_preset_voices(
                preset['speechVoices'], target_os
            )

    return config


def _build_init_script(values: Dict[str, Any]) -> str:
    """
    Builds the JavaScript init script that calls per-context window.setXxx() functions.
    These functions self-destruct after first call, so they must run via addInitScript.
    """
    import json as _json

    lines = ['(function(v) {', '  var w = window;']

    setters = [
        ('audioFingerprintSeed', 'setAudioFingerprintSeed', '{val}'),
        ('navigatorPlatform', 'setNavigatorPlatform', '{val}'),
        ('navigatorOscpu', 'setNavigatorOscpu', '{val}'),
        ('navigatorUserAgent', 'setNavigatorUserAgent', '{val}'),
        ('hardwareConcurrency', 'setNavigatorHardwareConcurrency', '{val}'),
        ('webglVendor', 'setWebGLVendor', '{val}'),
        ('webglRenderer', 'setWebGLRenderer', '{val}'),
    ]

    for key, fn_name, _template in setters:
        val = values.get(key)
        if val is not None:
            js_val = _json.dumps(val)
            lines.append(
                f'  if (typeof w.{fn_name} === "function") w.{fn_name}({js_val});'
            )

    # Screen dimensions (requires width + height together)
    sw = values.get('screenWidth')
    sh = values.get('screenHeight')
    if sw and sh:
        lines.append(
            f'  if (typeof w.setScreenDimensions === "function") w.setScreenDimensions({sw}, {sh});'
        )
        scd = values.get('screenColorDepth')
        if scd:
            lines.append(
                f'  if (typeof w.setScreenColorDepth === "function") w.setScreenColorDepth({scd});'
            )

    # Timezone — only call setTimezone() when we have an explicit value.
    # Without this, the C++ MaskConfig fallback (from CAMOU_CONFIG set by geoip
    # in launch_options) handles timezone for both main thread and workers via
    # SetNewDocument() and TimezoneManager::GetTimezone().
    # The old fallback read system TZ and poisoned RoverfoxStorageManager,
    # preventing MaskConfig from ever being consulted.
    tz = values.get('timezone')
    if tz:
        lines.append(
            f'  if (typeof w.setTimezone === "function") w.setTimezone({_json.dumps(tz)});'
        )

    # WebRTC IP
    ip = values.get('webrtcIP')
    if ip:
        validate_ip(ip)
        fn_name = 'setWebRTCIPv4' if valid_ipv4(ip) else 'setWebRTCIPv6'
        lines.append(
            f'  if (typeof w.{fn_name} === "function") w.{fn_name}({_json.dumps(ip)});'
        )
    else:
        lines.append(
            '  if (typeof w.setWebRTCIPv4 === "function") w.setWebRTCIPv4("");'
        )

    # Font list (comma-separated)
    font_list = values.get('fontList')
    if font_list and len(font_list) > 0:
        joined = ','.join(font_list)
        lines.append(
            f'  if (typeof w.setFontList === "function") w.setFontList({_json.dumps(joined)});'
        )

    # Speech voices (comma-separated names). config['voices'] holds MaskConfig
    # voice objects; extract the display name from each (tolerating a legacy
    # list of plain name strings).
    voices = values.get('speechVoices')
    if voices and len(voices) > 0:
        names = [v['name'] if isinstance(v, dict) else v for v in voices]
        joined = ','.join(names)
        lines.append(
            f'  if (typeof w.setSpeechVoices === "function") w.setSpeechVoices({_json.dumps(joined)});'
        )

    lines.append('})();')
    return '\n'.join(lines)


def generate_context_fingerprint(
    preset: Optional[Dict] = None,
    os: Optional[str] = None,
    ff_version: Optional[str] = None,
    webrtc_ip: Optional[str] = None,
    timezone: Optional[str] = None,
    locale: Optional[str] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate fingerprint values for a single per-context identity.
    Returns a dict with init_script (JS string) and context_options (Playwright options).

    By default, fpgen generates a unique synthetic fingerprint.
    Pass a preset dict to use a real fingerprint preset instead.

    Parameters:
        timezone: IANA timezone string (e.g. 'Europe/London'). When provided,
            injected into config before init_script generation. Takes priority
            over any timezone from the preset.
        locale: BCP-47 locale string (e.g. 'en-GB'). When provided, parsed via
            normalize_locale() and injected into config. Also sets
            context_options['locale'] for Playwright.
        config_overrides: Dict of CAMOU_CONFIG keys to override after config
            is built but before init_script is rendered (e.g. {'audio:seed': 7}).
    """
    if preset is not None:
        # Use real fingerprint preset
        config = from_preset(preset, ff_version)
        nav = preset.get('navigator', {})
        screen = preset.get('screen', {})
        webgl = preset.get('webgl', {})
    else:
        # Fall back to synthetic generation
        fp = generate_fingerprint(os=os)
        config = from_fpgen(fp, ff_version)
        # fpgen's Linux pool now and then pairs the Linux UA with a Windows
        # platform and oscpu. launch_options() corrects that; this path did
        # not, so ~1.6% of Linux contexts said Win32 -- and, since the OS below
        # is read from the platform, drew Windows fonts and voices as well.
        if 'Linux' in str(config.get('navigator.userAgent', '')):
            fix_navigator_arch(config, 'lin')

        # A fresh identity: every seeded draw below gets its own salt.
        _salt = identity_salt()

        # Add seeds (the generator doesn't produce these)
        config.setdefault('audio:seed', randint(1, 4_294_967_295))  # nosec

        # Determine target OS from platform for font/voice generation
        plat = config.get('navigator.platform', '')
        os_name = 'macos'
        if plat == 'Win32':
            os_name = 'windows'
        elif 'Linux' in plat or 'linux' in plat:
            os_name = 'linux'

        # Add fonts (fpgen.yml does not map these yet)
        if 'fonts' not in config:
            try:
                config['fonts'] = _generate_random_font_subset(os_name, seed=identity_seed(config, _salt))
            except (OSError, ValueError) as e:
                FallbackWarning.warn(
                    'Drawing the font list', "the browser's launch-time fonts", e,
                    config.get('navigator.userAgent'),
                )

        # Add voices (fpgen.yml does not map these yet)
        if 'voices' not in config:
            try:
                config['voices'] = _generate_random_voice_subset(os_name, seed=identity_seed(config, _salt))
            except (OSError, ValueError, KeyError) as e:
                FallbackWarning.warn(
                    'Drawing the speech voices', "the browser's launch-time voices", e,
                    config.get('navigator.userAgent'),
                )

        # Derive oscpu if the fingerprint didn't provide it
        if 'navigator.oscpu' not in config:
            plat = config.get('navigator.platform', '')
            if plat == 'MacIntel':
                config['navigator.oscpu'] = 'Intel Mac OS X 10.15'
            elif plat == 'Win32':
                config['navigator.oscpu'] = 'Windows NT 10.0; Win64; x64'
            elif 'Linux' in plat or 'linux' in plat:
                config['navigator.oscpu'] = 'Linux x86_64'

        # Draw the GPU and its WebGL data (fpgen.yml does not map these)
        if not config.get('webGl:vendor') or not config.get('webGl:renderer'):
            # Not at the top: camoufox.webgl imports this module.
            from .webgl import sample_webgl_for_screen

            _os_map = {'macos': 'mac', 'linux': 'lin', 'windows': 'win'}
            _target_os = _os_map.get(os or '', None)
            if not _target_os:
                plat = config.get('navigator.platform', '')
                if plat == 'Win32':
                    _target_os = 'win'
                elif 'Linux' in plat or 'linux' in plat:
                    _target_os = 'lin'
                else:
                    _target_os = 'mac'
            # Same coherence treatment launch_options applies (#729): lift
            # netbook geometry, then keep the GPU consistent with whatever
            # screen this identity ended up with. This path has no real
            # display to reconcile against, so the floor is unconditional.
            raise_screen_to_modern_floor(config)
            webgl_fp = sample_webgl_for_screen(
                _target_os, config.get('screen.width'), config.get('screen.height'),
                cores=config.get('navigator.hardwareConcurrency'),
            )
            webgl_fp.pop('webGl2Enabled')
            config.update(webgl_fp)

        # Build source dicts from the fingerprint config for init_values
        nav = {
            'platform': config.get('navigator.platform'),
            'hardwareConcurrency': config.get('navigator.hardwareConcurrency'),
        }
        screen = {
            'width': config.get('screen.width'),
            'height': config.get('screen.height'),
            'colorDepth': config.get('screen.colorDepth'),
            'devicePixelRatio': None,
        }
        webgl = {
            'unmaskedVendor': config.get('webGl:vendor'),
            'unmaskedRenderer': config.get('webGl:renderer'),
        }
        preset = {'navigator': nav, 'screen': screen, 'webgl': webgl}

    # Inject explicit timezone/locale into config (takes priority over preset)
    if timezone:
        config['timezone'] = timezone
    if locale:
        from .locales import normalize_locale
        parsed = normalize_locale(locale)
        config['locale:language'] = parsed.language
        config['locale:region'] = parsed.region
        config['navigator.language'] = parsed.as_string
        if parsed.script:
            config['locale:script'] = parsed.script

    # Apply caller overrides before rendering init_script
    if config_overrides:
        config.update(config_overrides)

    # Build the values dict for the init script (works for both paths)
    init_values: Dict[str, Any] = {
        'audioFingerprintSeed': config.get('audio:seed'),
        'navigatorPlatform': nav.get('platform'),
        'navigatorOscpu': config.get('navigator.oscpu'),
        'navigatorUserAgent': config.get('navigator.userAgent'),
        'hardwareConcurrency': nav.get('hardwareConcurrency') or config.get('navigator.hardwareConcurrency'),
        'webglVendor': webgl.get('unmaskedVendor'),
        'webglRenderer': webgl.get('unmaskedRenderer'),
        'screenWidth': screen.get('width'),
        'screenHeight': screen.get('height'),
        'screenColorDepth': screen.get('colorDepth'),
        'timezone': preset.get('timezone') if isinstance(preset.get('timezone'), str) else config.get('timezone'),
        'fontList': config.get('fonts'),
        'speechVoices': config.get('voices'),
        'webrtcIP': webrtc_ip or '',
    }

    init_script = _build_init_script(init_values)

    # Playwright context options that must be set at context creation
    context_options: Dict[str, Any] = {}
    ua = config.get('navigator.userAgent')
    if ua:
        context_options['user_agent'] = ua
    sw = screen.get('width')
    sh = screen.get('height')
    if sw and sh:
        context_options['viewport'] = {
            'width': sw,
            'height': max(sh - 28, 600),
        }
    dpr = screen.get('devicePixelRatio')
    if dpr:
        context_options['device_scale_factor'] = dpr
    tz = config.get('timezone')
    if not tz and isinstance(preset, dict):
        tz = preset.get('timezone')
    if tz:
        context_options['timezone_id'] = tz
    nav_lang = config.get('navigator.language')
    if nav_lang:
        context_options['locale'] = nav_lang

    return {
        'init_script': init_script,
        'context_options': context_options,
        'config': config,
        'preset': preset,
    }


def _cast_to_properties(
    camoufox_data: Dict[str, Any],
    cast_enum: Dict[str, Any],
    bf_dict: Dict[str, Any],
    ff_version: Optional[str] = None,
) -> None:
    """
    Casts a generated fingerprint to Camoufox config properties.
    """
    for key, data in bf_dict.items():
        # Ignore non-truthy values
        if not data:
            continue
        # Get the associated Camoufox property
        type_key = cast_enum.get(key)
        if not type_key:
            continue
        # If the value is a dictionary, recursively recall
        if isinstance(data, dict):
            _cast_to_properties(camoufox_data, type_key, data, ff_version)
            continue
        # fpgen carries header values as a list of the values seen for that
        # header; a single one is the header itself, and the config wants the
        # string. More than one is ambiguous, so take none of them.
        if isinstance(data, list):
            if len(data) == 1 and isinstance(data[0], str):
                data = data[0]
            else:
                continue
        # Fix values that are out of bounds
        if type_key.startswith("screen.") and isinstance(data, int) and data < 0:
            data = 0
        # Replace the Firefox versions with ff_version
        if ff_version and isinstance(data, str):
            data = re.sub(r'(?<!\d)(1[0-9]{2})(\.0)(?!\d)', rf'{ff_version}\2', data)
        camoufox_data[type_key] = data


def handle_screenXY(camoufox_data: Dict[str, Any], fingerprint: Dict[str, Any]) -> None:
    """
    Helper method to set window.screenY based on the generated screenX value.
    """
    # Skip if manually provided
    if 'window.screenY' in camoufox_data:
        return
    screen = fingerprint.get('screen') or {}
    window = fingerprint.get('window') or {}
    # Default screenX to 0 if not provided
    screenX = window.get('screenX')
    if not screenX:
        camoufox_data['window.screenX'] = 0
        camoufox_data['window.screenY'] = 0
        return

    # If screenX is within [-50, 50], use the same value for screenY
    if screenX in range(-50, 51):
        camoufox_data['window.screenY'] = screenX
        return

    # The generator thinks the browser is windowed. Randomly generate a screenY.
    screenY = (screen.get('availHeight') or 0) - (window.get('outerHeight') or 0)
    if screenY == 0:
        camoufox_data['window.screenY'] = 0
    elif screenY > 0:
        camoufox_data['window.screenY'] = randrange(0, screenY)  # nosec
    else:
        camoufox_data['window.screenY'] = randrange(screenY, 0)  # nosec


def from_fpgen(fingerprint: Dict[str, Any], ff_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Converts an fpgen fingerprint to a Camoufox config.
    """
    camoufox_data: Dict[str, Any] = {}
    _cast_to_properties(
        camoufox_data,
        cast_enum=FPGEN_DATA,
        bf_dict=fingerprint,
        ff_version=ff_version,
    )
    handle_screenXY(camoufox_data, fingerprint)

    return camoufox_data


def handle_window_size(fp: Dict[str, Any], outer_width: int, outer_height: int) -> None:
    """
    Helper method to set a custom outer window size, and center it in the screen
    """
    screen = fp.setdefault('screen', {})
    window = fp.setdefault('window', {})

    # Center the window on the screen
    window['screenX'] = (window.get('screenX') or 0) + (
        (screen.get('width') or outer_width) - outer_width
    ) // 2
    window['screenY'] = ((screen.get('height') or outer_height) - outer_height) // 2

    # Update inner dimensions if set
    if window.get('innerWidth'):
        window['innerWidth'] = max(
            outer_width - (window.get('outerWidth') or 0) + window['innerWidth'], 0
        )
    if window.get('innerHeight'):
        window['innerHeight'] = max(
            outer_height - (window.get('outerHeight') or 0) + window['innerHeight'], 0
        )

    # Set outer dimensions
    window['outerWidth'] = outer_width
    window['outerHeight'] = outer_height


def generate_fingerprint(
    window: Optional[Tuple[int, int]] = None,
    screen: Optional[Screen] = None,
    os: Optional[Any] = None,
    **conditions: Any,
) -> Dict[str, Any]:
    """
    Generates a Firefox fingerprint with fpgen.

    `screen` bounds the generated screen; `window` overrides the outer window
    size afterwards. `os` is Camoufox's name for the platform ('linux', 'macos',
    'windows', or several); anything else is passed to fpgen as a condition.
    """
    if os:
        names = [os] if isinstance(os, str) else list(os)
        try:
            resolved = [_FPGEN_OS[str(n).lower()] for n in names]
        except KeyError as exc:
            raise ValueError(f'Unknown OS for fingerprint generation: {exc.args[0]!r}') from None
        # fpgen takes one value or a predicate, not a list of alternatives.
        conditions['os'] = resolved[0] if len(resolved) == 1 else (lambda v: v in set(resolved))
    screen_conditions = screen.as_conditions() if screen is not None else {}
    try:
        fingerprint = _generator().generate(browser='Firefox', **conditions, **screen_conditions)
    except Exception as exc:  # fpgen.exceptions.InvalidConstraints
        if not screen_conditions or type(exc).__name__ != 'InvalidConstraints':
            raise
        # The screen bound is best-effort, as it was under BrowserForge, which
        # dropped a constraint that filtered its pool empty instead of raising.
        # It comes from the real display (get_screen_cons), and a display the
        # pool has nothing to fit -- a 1x1 Xvfb, an unusually small panel --
        # must not stop a fingerprint being generated. clamp_screen_to_display()
        # still bounds the result afterwards.
        fingerprint = _generator().generate(browser='Firefox', **conditions)

    if window:  # User-specified outer window size
        handle_window_size(fingerprint, *window)
    return fingerprint


if __name__ == "__main__":
    from pprint import pprint

    fp = generate_fingerprint()
    pprint(from_fpgen(fp))
