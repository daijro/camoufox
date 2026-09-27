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
from typing import Any, Dict, FrozenSet, Optional, Tuple

import orjson

from .coherence import gpu_fits_machine, gpu_fits_os
from .fingerprints import _FPGEN_OS, gpu_screen_is_plausible, is_software_renderer
from .fpgen_model import load_fpgen

# Extensions a release Firefox never exposes (draft extensions behind
# webgl.enable-draft-extensions, or mobile-only): fpgen's corpus carries some
# of them, and a spoofed list that names one is a tell on its own. Measured on
# stock Firefox 152.0.4 on real Windows 11 (ANGLE D3D11) 2026-09-16: none of
# these four are exposed. WEBGL_provoking_vertex is NOT in this set: stock
# Firefox on Apple GPUs and on Windows does expose it.
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


def _context_config(prefix: str, webgl: Dict[str, Any], target_os: str) -> Dict[str, Any]:
    blocked = _filtered_extensions(target_os)
    return {
        f'{prefix}:contextAttributes': webgl['contextAttributes'],
        f'{prefix}:supportedExtensions': [
            extension for extension in webgl['supportedExtensions'] if extension not in blocked
        ],
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
    config = {
        'webGl:vendor': webgl['vendor'],
        'webGl:renderer': webgl['renderer'],
        **_context_config('webGl', webgl, target_os),
        'webGl2Enabled': bool(webgl2),
    }
    if webgl2:
        config.update(_context_config('webGl2', webgl2, target_os))
    # The values are fpgen's cached objects; the caller gets its own copy.
    return orjson.loads(orjson.dumps(config))


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
