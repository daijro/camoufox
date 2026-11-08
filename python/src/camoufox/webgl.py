"""WebGL identities, drawn from the Firefox devices fpgen has recorded.

Everything a page can read from WebGL -- vendor, renderer, context attributes,
extensions, parameters and shader precisions, for WebGL1 and WebGL2 -- comes
from one recorded device. fpgen's `webgl` node is conditioned on the GPU, and
`webgl2` on the GPU and the `webgl` chosen for it, so a WebGL2 limit never
contradicts its WebGL1 counterpart.

Every draw takes one `random.Random`, in a fixed order (GPU, then webgl, then
webgl2), so a seeded identity always presents the same device.
"""

from functools import lru_cache
from random import Random
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import orjson

from .coherence import gpu_fits_machine, gpu_fits_os
from .fingerprints import _FPGEN_OS, gpu_screen_is_plausible, is_software_renderer
from .fpgen_model import load_fpgen

# Extensions a release Firefox never exposes (draft extensions behind
# webgl.enable-draft-extensions, or mobile-only): fpgen's corpus carries some
# of them, and a spoofed list that names one is a tell on its own. Measured on
# stock Firefox 152.0.4 on real Windows 11 (ANGLE D3D11) 2026-09-16: none of
# these four are exposed. WEBGL_provoking_vertex is NOT in this set: stock
# Firefox on Apple GPUs and on Windows does expose it. EXT_texture_norm16 left
# draft in Firefox 159; where it is exposed, _TEXTURE_NORM16 adds it back.
_NEVER_EXPOSED_EXTENSIONS = frozenset(
    {
        'WEBGL_multi_draw',
        'WEBGL_clip_cull_distance',
        'EXT_texture_norm16',
        'WEBGL_compressed_texture_etc1',
    }
)

# OVR_multiview2 is a RELEASE extension whose availability depends on the
# graphics backend. On Windows, Firefox renders WebGL through ANGLE's D3D11
# backend, which implements multiview on every D3D11 GPU: stock 152.0.4 on a
# Windows 11 host exposes it on WebGL2 (MAX_VIEWS_OVR=4, headless and headed),
# and fpgen records it on ~99% of Windows WebGL2 devices -- filtering it there
# was a leak. On Linux it depends on the host GL driver (stock on an NVIDIA box
# does not expose it), and ClientWebGLContext::IsSupported answers from the
# spoofed list without asking the host, so a Linux identity could advertise an
# extension the GPU cannot back; it stays filtered off Windows.
_HOST_DEPENDENT_EXTENSIONS = frozenset({'OVR_multiview2'})

# Extensions the claimed OS's backend exposes on every GPU in Firefox 156,
# which fpgen's Firefox 146 records lack. ANGLE sets depthClampEXT
# unconditionally on D3D11 (renderer11_utils.cpp); 146's ANGLE did not.
_BACKEND_EXTENSIONS = {'win': ('EXT_depth_clamp',)}

# Firefox 158 (bug 1854003) exposes EXT_polygon_offset_clamp wherever the GL
# backend clamps polygon offsets: ANGLE's D3D11 backend from feature level 10_0,
# which WebGL2 needs, and Linux desktop GL drivers (ARB_polygon_offset_clamp,
# core in GL 4.6), whose recordings have EXT_depth_clamp. macOS release builds
# run WebGL on CGL's GL 4.1, which lacks it.
_POLYGON_OFFSET_CLAMP = 'EXT_polygon_offset_clamp'

# Firefox 159 (bug 1735401) exposes EXT_texture_norm16 on WebGL2 wherever the
# GL has 16-bit normalized textures, core in desktop GL 3.1: every WebGL2
# context on macOS (CGL's GL 4.1) and x86_64 Linux (desktop GL). On Windows,
# ANGLE decides per device from its D3D11 format support, which no recording
# carries, so it stays filtered there.
_TEXTURE_NORM16 = 'EXT_texture_norm16'
_TEXTURE_NORM16_OSES = ('mac', 'lin')

# Firefox 159 adds EXT_clip_control (core in GL 4.5) and
# EXT_texture_mirror_clamp_to_edge (core in GL 4.4) to WebGL1 and WebGL2. ANGLE's
# D3D11 backend sets clipControlEXT from feature level 10_0, which WebGL2 needs,
# and textureMirrorClampToEdgeEXT on every device (renderer11_utils.cpp). Linux
# desktop GL drivers, whose recordings have EXT_depth_clamp, expose both. CGL's
# GL 4.1 on macOS has neither.
_CLIP_CONTROL = 'EXT_clip_control'
_TEXTURE_MIRROR_CLAMP_TO_EDGE = 'EXT_texture_mirror_clamp_to_edge'

_ALIASED_LINE_WIDTH_RANGE = '33902'

# Firefox 159 caps this at 64 KiB (WebGL2ContextState.cpp, kMaxUniformBlockSize);
# fpgen recorded the drivers' own limit, up to 4 GiB.
_MAX_UNIFORM_BLOCK_SIZE = '35376'
_MAX_UNIFORM_BLOCK_SIZE_CAP = 64 * 1024

# What Firefox reports under privacy.resistFingerprinting. A Camoufox identity
# presents none of RFP's other changes (UTC, rounded windows), so "Mozilla"
# beside them names a browser that does not exist.
_RFP_RENDERER = 'Mozilla'


def _filtered_extensions(target_os: str) -> FrozenSet[str]:
    if target_os == 'win':
        return _NEVER_EXPOSED_EXTENSIONS
    return _NEVER_EXPOSED_EXTENSIONS | _HOST_DEPENDENT_EXTENSIONS


@lru_cache(maxsize=None)
def _lookup_index(node: str) -> Dict[str, str]:
    """fpgen's lookup index for every value of `node`, keyed by its JSON."""
    return load_fpgen().utils._lookup_possibilities(node, casefold=False)


def _pin(node: str, value: Any) -> Tuple[str, str]:
    """Evidence fixing `node` to exactly `value`.

    A dict passed to fpgen as a condition is flattened into one condition per
    leaf, and each leaf replaces the node's evidence, so only the last one
    applies ("Mesa" and "AMD" Radeon HD 3200 would come back mixed). Pinning
    the value's own lookup index is exact.
    """
    return node, _lookup_index(node)[orjson.dumps(value).decode()]


@lru_cache(maxsize=None)
def _trace(target: str, target_os: str, pinned: Tuple[Tuple[str, str], ...] = ()) -> Tuple[Any, ...]:
    """fpgen's distribution of `target` for Firefox on `target_os`, in its order."""
    return tuple(
        load_fpgen().trace(
            target=target,
            browser='Firefox',
            os=_FPGEN_OS[target_os],
            __evidence__={node: {index} for node, index in pinned},
        )
    )


def _choose(rng: Random, results: Tuple[Any, ...]) -> Any:
    return rng.choices(results, weights=[result.probability for result in results])[0].value


def firefox_gpus(target_os: str) -> FrozenSet[Tuple[str, str]]:
    """Every (vendor, renderer) that fpgen has seen Firefox report on this OS.

    A GPU outside this set has no recorded WebGL parameters behind it, so an
    identity naming it could only borrow another device's.
    """
    return frozenset(
        (result.value['vendor'], result.value['renderer'])
        for result in _trace('gpu', target_os.lower())
    )


def _backend_extensions(target_os: str, webgl: Dict[str, Any], webgl2: Any) -> Tuple[str, ...]:
    """The extensions the shipped Firefox adds on this device's backend."""
    extensions = _BACKEND_EXTENSIONS.get(target_os, ())
    desktop_gl = target_os == 'lin' and 'EXT_depth_clamp' in webgl['supportedExtensions']
    if (target_os == 'win' and webgl2) or desktop_gl:
        extensions += (_POLYGON_OFFSET_CLAMP, _CLIP_CONTROL)
    if target_os == 'win' or desktop_gl:
        extensions += (_TEXTURE_MIRROR_CLAMP_TO_EDGE,)
    return extensions


def _context_config(
    prefix: str, webgl: Dict[str, Any], target_os: str, backend: Tuple[str, ...]
) -> Dict[str, Any]:
    blocked = _filtered_extensions(target_os)
    extensions = [extension for extension in webgl['supportedExtensions'] if extension not in blocked]
    for extension in backend:
        if extension not in extensions:
            # Firefox lists them in WebGLExtensionID order: alphabetical, ignoring case.
            at = next((i for i, other in enumerate(extensions) if other.casefold() > extension.casefold()), None)
            extensions.insert(len(extensions) if at is None else at, extension)
    return {
        f'{prefix}:supportedExtensions': extensions,
        f'{prefix}:parameters': {pname: param['value'] for pname, param in webgl['params'].items()},
        f'{prefix}:shaderPrecisionFormats': {
            f"{entry['shaderType']},{entry['precisionType']}": entry['shaderPrecisionFormat']
            for entry in webgl['shaderPrecisionFormats']
        },
    }


def to_config(webgl: Dict[str, Any], webgl2: Any, target_os: str) -> Dict[str, Any]:
    """fpgen's `webgl` and `webgl2` values as Camoufox config keys.

    `webgl2` is `[]` for a device without WebGL2.
    """
    backend = _backend_extensions(target_os, webgl, webgl2)
    config = {
        'webGl:vendor': webgl['vendor'],
        'webGl:renderer': webgl['renderer'],
        **_context_config('webGl', webgl, target_os, backend),
        'webGl2Enabled': bool(webgl2),
    }
    if webgl2:
        if target_os in _TEXTURE_NORM16_OSES:
            backend += (_TEXTURE_NORM16,)
        config.update(_context_config('webGl2', webgl2, target_os, backend))
        # Firefox 156 creates WebGL1 on the same GL profile as WebGL2, so both
        # report one line width range. 146 forced WebGL1 onto a compatibility
        # profile, and fpgen recorded that profile's driver range.
        config['webGl:parameters'][_ALIASED_LINE_WIDTH_RANGE] = config['webGl2:parameters'][_ALIASED_LINE_WIDTH_RANGE]
        parameters = config['webGl2:parameters']
        if _MAX_UNIFORM_BLOCK_SIZE in parameters:
            parameters[_MAX_UNIFORM_BLOCK_SIZE] = min(parameters[_MAX_UNIFORM_BLOCK_SIZE], _MAX_UNIFORM_BLOCK_SIZE_CAP)
    # The values are fpgen's cached objects; the caller gets its own copy.
    return orjson.loads(orjson.dumps(config))


def recorded_devices(target_os: str, vendor: str, renderer: str) -> List[Dict[str, Any]]:
    """Every device fpgen recorded behind this GPU from Firefox on `target_os`,
    as the launchers configure it."""
    gpu_pin = _pin('gpu', {'vendor': vendor, 'renderer': renderer})
    return [
        to_config(webgl.value, webgl2.value, target_os)
        for webgl in _trace('webgl', target_os, (gpu_pin,))
        for webgl2 in _trace('webgl2', target_os, (gpu_pin, _pin('webgl', webgl.value)))
    ]


def _webgl_config(target_os: str, gpu: Dict[str, str], rng: Random) -> Dict[str, Any]:
    gpu_pin = _pin('gpu', gpu)
    webgl = _choose(rng, _trace('webgl', target_os, (gpu_pin,)))
    webgl2 = _choose(rng, _trace('webgl2', target_os, (gpu_pin, _pin('webgl', webgl))))
    return to_config(webgl, webgl2, target_os)


def webgl_for_gpu(target_os: str, vendor: str, renderer: str, seed: Optional[int] = None) -> Dict[str, Any]:
    """The WebGL config of a device with this GPU, as Firefox on `target_os` reports it.

    Raises ValueError for a GPU fpgen has never seen Firefox report on that OS:
    it has no recorded parameters, and another device's would contradict it.
    """
    if (vendor, renderer) not in firefox_gpus(target_os):
        raise ValueError(
            f'No recorded WebGL data for vendor {vendor!r} and renderer {renderer!r} '
            f'from Firefox on {_FPGEN_OS[target_os]}. Possible pairs: '
            f'{sorted(firefox_gpus(target_os))}'
        )
    return _webgl_config(target_os, {'vendor': vendor, 'renderer': renderer}, Random(seed))


def sample_webgl_for_screen(
    target_os: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    seed: Optional[int] = None,
    cores: Optional[int] = None,
) -> Dict[str, Any]:
    """Draw a GPU for a synthetic identity, weighted as fpgen records Firefox
    on `target_os`, and its WebGL config.

    Only GPUs the rest of the identity can stand beside are drawn: never a
    software rasteriser, a GPU the OS cannot report, the resistFingerprinting
    mask, a discrete GPU behind a netbook panel (see gpu_screen_is_plausible),
    or an Intel Mac GPU beside cores or a panel no Intel Mac has
    (coherence.gpu_fits_machine).
    The screen is left alone: it has already been reconciled with the real
    display and the window (#499).

    Software rasterisers cost fidelity -- real users do run without working
    drivers -- but "no consumer machine reports llvmpipe" is a live, standard
    check on a string every fingerprint script reads (sundial, 2026-09-14).
    A host that really renders in software claims its renderer instead
    (plan_rendering).
    """
    candidates = tuple(
        result
        for result in _trace('gpu', target_os)
        if not is_software_renderer(result.value['renderer'])
        and result.value['renderer'] != _RFP_RENDERER
        and gpu_fits_os(result.value['renderer'], target_os)
        and gpu_fits_machine(result.value['renderer'], target_os, cores, width, height)
        and gpu_screen_is_plausible(result.value['renderer'], width, height)
    )
    if not candidates:
        raise ValueError(f'No recorded {target_os} GPU fits a {width}x{height} screen')
    rng = Random(seed)
    return _webgl_config(target_os, _choose(rng, candidates), rng)
