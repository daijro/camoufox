import json
import os
import platform
import shutil
from functools import wraps
from os import environ
from os.path import abspath
from pathlib import Path
from pprint import pprint
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union

import numpy as np
import orjson
from typing_extensions import TypeAlias
from ua_parser import user_agent_parser

from .addons import DefaultAddons, add_default_addons, confirm_paths
from .display import has_display, largest_display
from .exceptions import (
    InvalidOS,
    InvalidPropertyType,
    NonFirefoxFingerprint,
)
from .fingerprints import Screen, platform_to_os, from_fpgen, from_preset, generate_fingerprint, get_random_preset, _generate_random_font_subset, _generate_random_voice_subset, fix_navigator_arch, fix_hardware_concurrency, identity_salt, identity_seed, follow_baseline_protection, clamp_screen_to_display, clamp_window_dimensions, clamp_window_position, raise_screen_to_modern_floor, set_media_devices_defaults, WINDOWS_11_MARKER_FONTS, OS_KEYS, OS_NAMES
from . import coherence
from .geolocation import geoip_allowed, get_geolocation
from .ip import Proxy, public_ip, valid_ipv4, valid_ipv6
from .locales import handle_locales
import warnings

from .pkgman import (
    INSTALL_DIR,
    LAUNCHER_CONSTANTS,
    OS_NAME,
    Version,
    build_file,
    effective_version_min,
    ensure_browser_profile_dir,
    get_path,
    installed_verstr,
    launch_path,
    selected_launch_path,
    warn_if_package_outdated,
)
from .virtdisplay import VirtualDisplay
from ._warnings import FallbackWarning, LeakWarning
from .host_rendering import Gpu, add_canvas_placeholder, has_canvas_placeholder, host_gpu, renders_on_hardware, set_webgpu
from .webgl import firefox_gpus, sample_webgl_for_screen, webgl_for_gpu

ListOrString: TypeAlias = Union[Tuple[str, ...], List[str], str]

# Camoufox preferences to cache previous pages and requests
CACHE_PREFS: Dict[str, Any] = LAUNCHER_CONSTANTS['cachePrefs']


def _host_os_key() -> Optional[str]:
    """The host OS in fonts.json / target_os terms ('mac', 'win', 'lin')."""
    return {'Darwin': 'mac', 'Windows': 'win', 'Linux': 'lin'}.get(platform.system())


# navigator.storage.estimate().quota is not a constant: Gecko derives it from
# the disk. GetTemporaryStorageLimit() (dom/quota/ActorsParent.cpp) takes
# nsIFile::GetDiskCapacity() of the storage directory and halves it, then
# QuotaManager::GetGroupLimitForLimit() reports min(that / 5, 10 GiB) to the
# page -- so any disk of 100 GB or more reads back as exactly 10 GiB, and a
# smaller one as its own capacity / 10.
_QUOTA_FIXED_LIMIT_PREF = 'dom.quotaManager.temporaryStorage.fixedLimit'
# The pref is a signed 32-bit int in KB. Any value above 50 GiB already reports
# the 10 GiB group cap, so clamping a multi-terabyte disk changes nothing a page
# can see.
_INT32_MAX = 2**31 - 1


def _stock_profile_disk_capacity_kb() -> Optional[int]:
    """Half the capacity of the disk a stock Firefox profile would live on, in KB.

    That is the number Gecko's own GetTemporaryStorageLimit() would compute on
    this machine, and it is what `dom.quotaManager.temporaryStorage.fixedLimit`
    takes. Capacity is always a multiple of the filesystem block size, so the
    KB conversion is exact rather than a rounding of it.

    The disk a stock profile lives on, not the one Playwright's throwaway
    profile lands on: on a host whose temp directory is a tmpfs, that profile
    sits on a RAM-sized volume no real Firefox profile would (measured here:
    3 189 253 734 from a 29.7 GiB /tmp, where the same machine's own Firefox
    reports 10 737 418 240).
    """
    home = Path.home()
    if OS_NAME == 'win':
        appdata = os.environ.get('APPDATA')
        candidates = [Path(appdata) / 'Mozilla' if appdata else home, home]
    elif OS_NAME == 'mac':
        candidates = [home / 'Library' / 'Application Support' / 'Firefox', home]
    else:
        candidates = [home / '.mozilla', home]

    for candidate in candidates:
        # The directory only exists if Firefox has ever run here; walk up to
        # the first path that does, which is on the same filesystem anyway.
        probe = candidate
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            total = shutil.disk_usage(probe).total
        except OSError:
            continue
        if total > 0:
            return min(total // 2 // 1024, _INT32_MAX)
    return None


def _generate_fontconfig(
    fontconfig_path: str, path: Optional[Path] = None, os_dir: Optional[str] = None
) -> str:
    """
    Generates a runtime fontconfig that resolves bundled font paths absolutely.
    The bundled fonts.conf uses prefix="cwd" relative paths which break when
    Playwright's working directory differs from the browser install directory.
    Writes a patched copy to the platform cache dir (deterministic, only
    regenerated when content changes). This must not live inside the versioned
    browser bundle: the bundle is commonly baked into an image as root and run
    as a non-root user, so it is read-only at launch time.
    """
    import hashlib

    # Beside the caller's own binary when they supplied one; see get_env_vars.
    fonts_dir = str(path.parent / "fonts") if path else get_path("fonts")

    # Which directories this identity's OS may see.
    #
    # fontconfig scans <dir> RECURSIVELY, so the parent must never be named: it
    # would make every other OS's files reachable by the renderer -- hidden by
    # the allowlist for direct lookups, but still candidates for glyph fallback
    # (an emoji or CJK glyph from Segoe UI Emoji / PingFang on a machine
    # claiming Linux).
    #
    # The bundle stores each face ONCE, in a directory named for the set of
    # OSes that use it (L, M, W, LM, LW, MW, LMW) -- see browser/bundle/fonts/groups.json
    # and browser/scripts/gen-font-groups.py. Storing per-OS instead meant 41% of the
    # bundle was byte-identical copies. An OS reads the four groups its letter
    # appears in, so nothing has to be hidden after the fact: a face Windows
    # must not see is simply not in a group Windows reads.
    scan_dirs = []
    groups_path = os.path.join(fonts_dir, "groups.json")
    os_key = OS_KEYS.get(os_dir or '')
    if os_key and os.path.exists(groups_path):
        try:
            with open(groups_path, 'rb') as fh:
                read_by = json.loads(fh.read()).get('readBy', {}).get(os_key, [])
            scan_dirs = [
                os.path.join(fonts_dir, g)
                for g in read_by
                if os.path.isdir(os.path.join(fonts_dir, g))
            ]
        except (OSError, ValueError):
            scan_dirs = []
    if not scan_dirs:
        # Older bundles ship fonts/<os>/ with each OS's set duplicated in full.
        if os_dir and os.path.isdir(os.path.join(fonts_dir, os_dir)):
            scan_dirs = [os.path.join(fonts_dir, os_dir)]
        else:
            scan_dirs = [fonts_dir]

    fonts_conf_src = os.path.join(fontconfig_path, "fonts.conf")

    with open(fonts_conf_src, 'r') as f:
        conf_content = f.read()

    conf_content = conf_content.replace(
        '<dir prefix="cwd">fonts</dir>',
        "\n\t".join(f'<dir>{d}</dir>' for d in scan_dirs),
    )

    # INSTALL_DIR is platformdirs' user_cache_dir("camoufox"); see pkgman.
    cache_dir = str(INSTALL_DIR / 'fontconfig')
    os.makedirs(cache_dir, exist_ok=True)

    content_hash = hashlib.sha256(conf_content.encode()).hexdigest()[:12]
    runtime_conf = os.path.join(cache_dir, f'fonts-{content_hash}.conf')
    if not os.path.exists(runtime_conf):
        with open(runtime_conf, 'w') as f:
            f.write(conf_content)

    return runtime_conf


def warn_if_executable_predates_playwright(path: Optional[Path]) -> None:
    """Warn when a caller's own binary is older than their Playwright needs.

    A managed install below the floor is simply upgraded (pkgman resolves it),
    but `executable_path` deliberately bypasses that -- the caller supplied the
    binary, so we neither replace it nor download another. That leaves the one
    pairing nothing checks: an old build driven by Playwright >= 1.61, which
    sends viewport fields the older Juggler schema rejects.

    This warns rather than raises, because the pairing is not always fatal.
    Camoufox defaults to no_viewport when it spoofs window dimensions
    (sync_api), and Playwright then never sends Browser.setDefaultViewport --
    so the default path works on an old build. It breaks only when a viewport
    is set explicitly, and then the error is a bare "Protocol error
    (Browser.setDefaultViewport)" with nothing pointing at the real cause.
    Refusing to launch would break setups that currently work.

    A build with no version.json beside it -- an unpackaged objdir build, say --
    tells us nothing, so it is left alone.
    """
    if path is None:
        return
    try:
        installed = Version.from_path(Path(path).parent)
    except (FileNotFoundError, KeyError, ValueError):
        return

    required = effective_version_min()
    if installed >= required:
        return

    warnings.warn(
        f"The Camoufox build at {path} is {installed.build}, but Playwright "
        f"{_resolved_playwright_version_str()} needs at least {required.build}. "
        "Contexts created with an explicit viewport will fail with "
        '"Protocol error (Browser.setDefaultViewport)". Update the build, or pin '
        "playwright<1.61.",
        RuntimeWarning,
        stacklevel=3,
    )


def _resolved_playwright_version_str() -> str:
    from importlib.metadata import version

    try:
        return version('playwright')
    except Exception:
        return 'the installed version'


def get_pref_env_vars(prefs: Dict[str, Any]) -> Dict[str, str]:
    """
    Pass the launcher's Firefox prefs to browser/settings/camoufox.cfg, which applies them
    at STARTUP (CAMOU_PREFS_1..N, chunked like CAMOU_CONFIG).

    Playwright's non-persistent launch writes no user.js: firefox_user_prefs only
    reach the browser at runtime, through juggler's Browser.enable, after startup.
    Anything Gecko reads during startup therefore raced or never applied -- e.g.
    intl.locale.requested lost the race against the parent's pre-created
    dom.properties string bundles on Windows (fr-FR validation messages English
    in 3 of 4 launches), and mirror-once prefs such as
    gfx.bundled-fonts.activate were ignored outright.
    """
    if not prefs:
        return {}
    # ASCII only: on Windows autoconfig's getenv() reads the environment through
    # the ANSI code page, which would mangle a raw UTF-8 pref value (\u escapes
    # survive it and JSON.parse restores them).
    data = json.dumps(prefs, ensure_ascii=True, separators=(',', ':'))
    chunk_size = 2047 if OS_NAME == 'win' else 32767
    return {
        f"CAMOU_PREFS_{(i // chunk_size) + 1}": data[i : i + chunk_size]
        for i in range(0, len(data), chunk_size)
    }


def get_env_vars(
    config_map: Dict[str, str],
    user_agent_os: str,
    path: Optional[Path] = None,
) -> Dict[str, Union[str, float, bool]]:
    """
    Gets a dictionary of environment variables for Camoufox.

    `path` is the caller's own executable, when they supplied one. The bundled
    fontconfig is read from beside that binary rather than from the managed
    install, the same way _load_properties() already treats properties.json:
    a caller running their own build should not be resolved against, or made
    to download, a different one.
    """
    env_vars: Dict[str, Union[str, float, bool]] = {}
    try:
        config_str = orjson.dumps(config_map).decode('utf-8')
    except orjson.JSONEncodeError as e:
        raise InvalidPropertyType(f"The config cannot be serialized to JSON: {e}") from e

    # Split the config into chunks
    chunk_size = 2047 if OS_NAME == 'win' else 32767
    for i in range(0, len(config_str), chunk_size):
        env_vars[f"CAMOU_CONFIG_{(i // chunk_size) + 1}"] = config_str[i : i + chunk_size]

    if OS_NAME == 'lin':
        # https://github.com/coryking/camoufox/commit/f21eeb2850a74cc104fb57e17e0a2fa27b7a2a28
        # Thanks @coryking
        # The fontconfig directories are named for the OS ('linux'), not its key ('lin').
        os_dir = OS_NAMES.get(user_agent_os, user_agent_os)

        # v150+ uses "fontconfig/"; older bundles shipped "fontconfigs/".
        def _bundle_path(*parts: str) -> str:
            if path:
                return str(path.parent.joinpath(*parts))
            return get_path(os.path.join(*parts))

        fontconfig_path = _bundle_path("fontconfig", os_dir)
        if not os.path.exists(os.path.join(fontconfig_path, "fonts.conf")):
            fontconfig_path = _bundle_path("fontconfigs", os_dir)

        if not os.path.exists(os.path.join(fontconfig_path, "fonts.conf")):
            raise FileNotFoundError(
                f"fonts.conf not found in {fontconfig_path}; the Camoufox bundle is incomplete."
            )

        env_vars['FONTCONFIG_FILE'] = _generate_fontconfig(fontconfig_path, path=path, os_dir=os_dir)

    return env_vars


def _load_properties(path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """
    Loads the properties.json file: property -> its entry. An entry with a
    "removed" field is a key the browser no longer reads; it stays declared so
    that older libraries, which reject undeclared keys, still launch.
    """
    prop_file = build_file(path, "properties.json") if path else get_path("properties.json")
    with open(prop_file, "rb") as f:
        prop_dict = orjson.loads(f.read())

    return {prop['property']: prop for prop in prop_dict}


def validate_config(config_map: Dict[str, str], path: Optional[Path] = None) -> None:
    """
    Validates the config map.
    """
    properties = _load_properties(path=path)

    for key, value in config_map.items():
        entry = properties.get(key)
        if not entry:
            print(f'Skipping unknown patch {key} : {value}')
            continue  # Not supported by this browser version: reported, then skipped
        if 'removed' in entry:
            print(f'Skipping {key}: removed in {entry["removed"]}, it has no effect')
            continue
        expected_type = entry['type']

        if not validate_type(value, expected_type):
            raise InvalidPropertyType(
                f"Invalid type for property {key}. Expected {expected_type}, got {type(value).__name__}"
            )

        if key == 'voices':
            validate_voices(value)


def validate_type(value: Any, expected_type: str) -> bool:
    """
    Validates the type of the value.
    """
    if expected_type == "str":
        return isinstance(value, str)
    elif expected_type == "int":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    elif expected_type == "uint":
        return (
            isinstance(value, int) or (isinstance(value, float) and value.is_integer())
        ) and value >= 0
    elif expected_type == "double":
        return isinstance(value, (float, int))
    elif expected_type == "bool":
        return isinstance(value, bool)
    elif expected_type == "array":
        return isinstance(value, list)
    elif expected_type == "dict":
        return isinstance(value, dict)
    else:
        return False


# The five fields MaskConfig::MVoices() requires of every `voices` entry. It
# skips anything missing one of them, so a bare "Name:lang:type" string or a
# half-filled object registers nothing -- and a voice list that registers
# nothing leaves the host's native voices exposed. Reject the bad shape here,
# before launch, instead of letting it degrade silently in the browser (#731).
VOICE_FIELDS: Tuple[str, ...] = ('lang', 'name', 'voiceUri', 'isDefault', 'isLocalService')


def validate_voices(voices: Any) -> None:
    """
    Validates that every `voices` entry is a complete voice object.
    """
    if not isinstance(voices, list):
        raise InvalidPropertyType(
            f"Invalid type for property voices. Expected array, got {type(voices).__name__}"
        )

    for index, voice in enumerate(voices):
        if not isinstance(voice, dict):
            raise InvalidPropertyType(
                f"Invalid voices[{index}]: expected an object with "
                f"{{{', '.join(VOICE_FIELDS)}}}, got {type(voice).__name__} "
                f"({voice!r}). Camoufox needs full voice objects, not names."
            )
        missing = [field for field in VOICE_FIELDS if field not in voice]
        if missing:
            raise InvalidPropertyType(
                f"Invalid voices[{index}]: missing {', '.join(missing)}. "
                f"Every voice needs {{{', '.join(VOICE_FIELDS)}}}."
            )


def get_target_os(config: Dict[str, Any]) -> Literal['mac', 'win', 'lin']:
    """
    Gets the OS from the config if the user agent is set,
    otherwise returns the OS of the current system.
    """
    if config.get("navigator.userAgent"):
        return determine_ua_os(config["navigator.userAgent"])
    return OS_NAME


def determine_ua_os(user_agent: str) -> Literal['mac', 'win', 'lin']:
    """
    Determines the OS from the user agent string.
    """
    parsed_ua = user_agent_parser.ParseOS(user_agent).get('family')
    if not parsed_ua:
        raise ValueError("Could not determine OS from user agent")
    if parsed_ua.startswith("Mac"):
        return "mac"
    if parsed_ua.startswith("Windows"):
        return "win"
    return "lin"


def get_screen_cons(headless: Optional[bool] = None) -> Optional[Screen]:
    """
    Determines a sane viewport size for Camoufox if being ran in headful mode.

    Bounds are CSS pixels, the unit Firefox lays its windows out in -- see
    camoufox.display for why that differs from the monitor's physical size.
    """
    if headless is True:
        return None  # Skip if headless
    display = largest_display()
    if display is None:
        return None  # Skip if the display can't be probed
    return Screen(max_width=display.width, max_height=display.height)


def update_fonts(config: Dict[str, Any], target_os: str) -> None:
    """
    Updates the fonts for the target OS.
    """
    with open(os.path.join(os.path.dirname(__file__), "fonts.json"), "rb") as f:
        fonts = orjson.loads(f.read())[target_os]

    # Merge with existing fonts
    if 'fonts' in config:
        config['fonts'] = np.unique(fonts + config['fonts']).tolist()
    else:
        config['fonts'] = fonts


def check_custom_fingerprint(fingerprint: Dict[str, Any]) -> None:
    """
    Asserts that the passed fingerprint is a valid Firefox fingerprint,
    and warns the user that passing their own fingerprint is not recommended.
    """
    # Check what the browser is
    user_agent = (fingerprint.get('navigator') or {}).get('userAgent') or ''
    browser_name = user_agent_parser.ParseUserAgent(user_agent).get('family', 'Non-Firefox')
    if browser_name != 'Firefox':
        raise NonFirefoxFingerprint(
            f'"{browser_name}" fingerprints are not supported in Camoufox. '
            'Using fingerprints from a browser other than Firefox WILL lead to detection. '
            'If this is intentional, pass `i_know_what_im_doing=True`.'
        )

    LeakWarning.warn('custom_fingerprint', False)


def check_valid_os(os: ListOrString) -> None:
    """
    Checks if the target OS is valid.
    """
    if not isinstance(os, str):
        for os_name in os:
            check_valid_os(os_name)
        return
    # Assert that the OS is lowercase
    if not os.islower():
        raise InvalidOS(f"OS values must be lowercase: '{os}'")
    # Assert that the OS is supported by Camoufox
    if os not in ('windows', 'macos', 'linux'):
        raise InvalidOS(f"Camoufox does not support the OS: '{os}'")


def merge_into(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    """
    Merges new keys/values from the source dictionary into the target dictionary.
    Given that the key does not exist in the target dictionary.
    """
    for key, value in source.items():
        if key not in target:
            target[key] = value


def set_into(target: Dict[str, Any], key: str, value: Any) -> None:
    """
    Sets a new key/value into the target dictionary.
    Given that the key does not exist in the target dictionary.
    """
    if key not in target:
        target[key] = value


def is_domain_set(
    config: Dict[str, Any],
    *properties: str,
) -> bool:
    """
    Checks if a domain is set in the config.
    """
    for prop in properties:
        # If the . prefix exists, check if the domain is a prefix of any key in the config
        if prop[-1] in ('.', ':'):
            if any(key.startswith(prop) for key in config):
                return True
        # Otherwise, check if the domain is a direct key in the config
        else:
            if prop in config:
                return True
    return False


def warn_manual_config(config: Dict[str, Any]) -> None:
    """
    Warns the user if they are manually setting properties that Camoufox already sets internally.
    """
    # Manual locale setting
    if is_domain_set(
        config, 'navigator.language', 'headers.Accept-Language', 'locale:'
    ):
        LeakWarning.warn('locale', False)
    # Manual geolocation and timezone setting
    if is_domain_set(config, 'geolocation:', 'timezone'):
        LeakWarning.warn('geolocation', False)
    # Manual User-Agent setting
    if is_domain_set(config, 'headers.User-Agent'):
        LeakWarning.warn('header-ua', False)
    # Manual navigator setting
    if is_domain_set(config, 'navigator.'):
        LeakWarning.warn('navigator', False)
    # Touchscreen digitizer spoofing. Called out separately from the blanket
    # navigator warning because the knock-on effects reach past navigator into
    # CSS pointer media queries and the TouchEvent interfaces.
    if is_domain_set(config, 'navigator.maxTouchPoints'):
        LeakWarning.warn('max_touch_points', False)
    if config.get('instantAnimations'):
        LeakWarning.warn('instant_animations', False)
    # Manual screen/window setting
    if is_domain_set(config, 'screen.', 'window.', 'document.body.'):
        LeakWarning.warn('viewport', False)


_WINDOW_DIM_KEYS = (
    'window.outerWidth',
    'window.outerHeight',
    'window.innerWidth',
    'window.innerHeight',
)


def _camou_config_blob(from_options: Dict[str, Any]) -> str:
    env = from_options.get('env') or {}
    chunks = [(int(k.rsplit('_', 1)[1]), v) for k, v in env.items() if k.startswith('CAMOU_CONFIG_')]
    return ''.join(v for _, v in sorted(chunks))


def pinned_core_count(from_options: Dict[str, Any]) -> Optional[int]:
    """The core count the browser must be pinned to for these launch options,
    or None: the identity's navigator.hardwareConcurrency when this host can
    honour it (see cpu_affinity), so a page measuring parallelism sees the
    reported number."""
    from .cpu_affinity import host_cores, supported

    blob = _camou_config_blob(from_options)
    if not blob or not supported():
        return None
    try:
        value = orjson.loads(blob).get('navigator.hardwareConcurrency')
    except (orjson.JSONDecodeError, AttributeError):
        return None
    cores = host_cores()
    if isinstance(value, int) and cores and 1 <= value < len(cores):
        return value
    return None


def driver_pid(playwright: Any) -> Optional[int]:
    """PID of the Playwright driver that will spawn the browser (its children
    inherit the CPU affinity we set on it)."""
    try:
        impl = getattr(playwright, '_impl_obj', playwright)
        return int(impl._connection._transport._proc.pid)
    except Exception:
        return None


def spoofs_window_dimensions(from_options: Dict[str, Any]) -> bool:
    """
    Whether the CAMOU_CONFIG in a set of launch options spoofs any window
    dimension. The config is chunked across CAMOU_CONFIG_<n> env vars, so
    reassemble it in index order before looking.
    """
    blob = _camou_config_blob(from_options)
    return any(key in blob for key in _WINDOW_DIM_KEYS)


# Playwright emulates four media features on every context it creates, whether
# or not the caller asked: `colorScheme` defaults to "light" and reducedMotion /
# forcedColors / contrast to their no-preference values. That is an override, not
# a passthrough -- the page then reports it whatever the host is set to, so a
# desktop in dark mode still reads `(prefers-color-scheme: light)`, where stock
# Firefox on that machine reads dark (measured 2026-09-18, headed on a private
# Xvfb with GTK_THEME=Adwaita:dark: stock dark, camoufox light, camoufox with
# these defaults dark). "no-override" is Playwright's own opt-out: it sends no
# emulation at all and the browser answers from the host.
STOCK_MEDIA_DEFAULTS = {
    'color_scheme': 'no-override',
    'reduced_motion': 'no-override',
    'forced_colors': 'no-override',
    'contrast': 'no-override',
}


def _wrap_context_factories(target: Any, adjust: Any) -> Any:
    """Run `adjust(kwargs)` before every new_page()/new_context() call on `target`."""
    for name in ('new_page', 'new_context'):
        original = getattr(target, name, None)
        if original is None:
            continue

        def wrap(original: Any) -> Any:
            @wraps(original)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                adjust(kwargs)
                # Works for both sync and async: async returns the coroutine
                # unawaited, and the caller awaits it as usual.
                return original(*args, **kwargs)

            return wrapper

        setattr(target, name, wrap(original))
    return target


def attach_stock_media_defaults(target: Any) -> Any:
    """Default new_page()/new_context() to the host's own media features.

    Explicit color_scheme= / reduced_motion= / forced_colors= / contrast= from
    the caller always wins; this only replaces Playwright's silent defaults.
    """

    def adjust(kwargs: Dict[str, Any]) -> None:
        for option, value in STOCK_MEDIA_DEFAULTS.items():
            kwargs.setdefault(option, value)

    return _wrap_context_factories(target, adjust)


def attach_desktop_only_warning(target: Any) -> Any:
    """Warn when new_page()/new_context() asks for is_mobile: Camoufox only has
    desktop identities, and Juggler ignores the option (TargetRegistry.js)."""

    def adjust(kwargs: Dict[str, Any]) -> None:
        if kwargs.get('is_mobile'):
            LeakWarning.warn('is_mobile')

    return _wrap_context_factories(target, adjust)


def attach_no_viewport_default(target: Any) -> Any:
    """
    Default new_page()/new_context() to no_viewport=True.

    Playwright applies a 1280x720 viewport by default, which makes Juggler ask
    the content window to become 1280x720 (TargetRegistry.updateViewportSize).
    When Camoufox is pinning the window to a spoofed size, that request can
    never be satisfied, and awaitViewportDimensions has no timeout -- so the
    second new_page() hangs forever (daijro/camoufox#666).

    With no_viewport, Juggler measures the window instead of resizing it, so the
    handshake resolves immediately and the page reports the spoofed dimensions
    exactly. Explicit viewport=/no_viewport= from the caller always wins.
    """

    def adjust(kwargs: Dict[str, Any]) -> None:
        if 'viewport' not in kwargs and 'no_viewport' not in kwargs:
            kwargs['no_viewport'] = True

    return _wrap_context_factories(target, adjust)


def persistent_context_options(from_options: Dict[str, Any], no_viewport_default: bool) -> Dict[str, Any]:
    """Launch options for launch_persistent_context(). The launch itself creates
    the context, so the defaults new_context() would get go into the options."""
    if no_viewport_default and not ('viewport' in from_options or 'no_viewport' in from_options):
        from_options = {**from_options, 'no_viewport': True}
    return {
        **{k: v for k, v in STOCK_MEDIA_DEFAULTS.items() if k not in from_options},
        **from_options,
    }


def attach_context_defaults(browser: Any, no_viewport_default: bool) -> None:
    """Give every new_page()/new_context() of `browser` Camoufox's defaults."""
    if no_viewport_default:
        attach_no_viewport_default(browser)
    attach_stock_media_defaults(browser)
    attach_desktop_only_warning(browser)


def plan_rendering(
    target_os: str,
    canvas_noise: Optional[bool],
    named_gpu: bool,
    webgl_disabled: bool,
    probe: Callable[[], Optional[Gpu]],
) -> Tuple[bool, Optional[Gpu]]:
    """Whether the canvas is covered, and the host GPU the identity claims.

    The canvas renders on the host, so the identity claims the host's GPU when
    it can: on the host's OS, with no GPU named, on a hardware GPU fpgen has
    recorded there. A software renderer matches any GPU, and with WebGL off no
    GPU is claimed. Any other identity contradicts the pixels, so the canvas is
    covered unless the caller chose canvas_noise=False.
    """
    if canvas_noise:
        return True, None
    if target_os == _host_os_key() and not named_gpu:
        host = None if webgl_disabled else probe()
        if not renders_on_hardware(host):
            return False, None
        if host in firefox_gpus(target_os):
            return False, host
    return canvas_noise is None, None


def host_identity(from_options: Dict[str, Any], canvas_noise: Optional[bool]) -> Optional[Tuple[str, Optional[Gpu]]]:
    """For a launch without the canvas placeholder, the machine its contexts must
    claim: the host's OS, and the host GPU it claims (plan_rendering). Only for
    the default canvas_noise=None; a caller who chose it, or built the options,
    keeps their contexts as they ask. Read before the launch, so a failed probe
    leaves no browser behind."""
    prefs = from_options.get('firefox_user_prefs', {})
    if canvas_noise is not None or has_canvas_placeholder(prefs):
        return None
    # Without the placeholder, the launch claimed the host's OS and no named GPU.
    host_os = _host_os_key()
    covered, gpu = plan_rendering(
        host_os, None, False, bool(prefs.get('webgl.disabled')),
        lambda: host_gpu(from_options['executable_path'], from_options['headless'], from_options['env']),
    )
    return None if covered else (host_os, gpu)


def context_identity(
    browser: Any, os: Optional[str], preset: Optional[Dict[str, Any]]
) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    """The OS and GPU a new context on `browser` claims (None: drawn).

    On a browser without the canvas placeholder they are the host's, since the
    canvas renders there; asking for anything else raises.
    """
    host_identity = vars(browser).get('_camoufox_host_identity')
    if host_identity is None:
        return os, None
    host_os, gpu = host_identity
    host_name = OS_NAMES[host_os]
    preset_os = platform_to_os(preset.get('navigator', {}).get('platform', '')) if preset else None
    preset_gpu = preset.get('webgl', {}) if preset else {}
    if (
        (os or host_name) != host_name
        or (preset_os or host_name) != host_name
        or (gpu and preset and (preset_gpu.get('unmaskedVendor'), preset_gpu.get('unmaskedRenderer')) != gpu)
    ):
        raise ValueError(
            f'This browser renders its canvas as this {host_name} machine, so its contexts claim it'
            f'{" and its GPU " + repr(gpu) if gpu else ""}. Launch it with canvas_noise=True to give '
            'a context another OS or GPU.'
        )
    return host_name, gpu


def new_context_options(
    fingerprint: Dict[str, Any],
    context_kwargs: Dict[str, Any],
    proxy: Optional[Dict[str, str]],
    geolocation: Optional[Dict[str, float]],
) -> Dict[str, Any]:
    """new_context() options for a generate_context_fingerprint() identity; the
    caller's own options win."""
    opts: Dict[str, Any] = {**fingerprint['context_options'], **context_kwargs}
    if proxy:
        opts['proxy'] = proxy
    if geolocation:
        opts['geolocation'] = geolocation
        opts.setdefault('permissions', ['geolocation'])
    return opts


async def async_attach_vd(
    browser: Any, virtual_display: Optional[VirtualDisplay] = None
) -> Any:  # type: ignore
    """
    Attaches the virtual display to the async browser cleanup
    """
    if not virtual_display:  # Skip if no virtual display is provided
        return browser

    _close = browser.close

    async def new_close(*args: Any, **kwargs: Any):
        try:
            await _close(*args, **kwargs)
        finally:
            virtual_display.kill()

    browser.close = new_close

    return browser


def sync_attach_vd(
    browser: Any, virtual_display: Optional[VirtualDisplay] = None
) -> Any:  # type: ignore
    """
    Attaches the virtual display to the sync browser cleanup
    """
    if not virtual_display:  # Skip if no virtual display is provided
        return browser

    _close = browser.close

    def new_close(*args: Any, **kwargs: Any):
        try:
            _close(*args, **kwargs)
        finally:
            virtual_display.kill()

    browser.close = new_close

    return browser


def resolve_verstr(executable_path: Optional[Path] = None) -> str:
    """The Firefox version of the build about to launch: the named executable's
    own application.ini, or the installed release. A named executable without
    one raises, since claiming another build's version would leak in the UA."""
    if not executable_path:
        return installed_verstr()
    ini = build_file(executable_path, 'application.ini')
    for line in ini.read_text(encoding='utf-8').splitlines():
        if line.startswith('Version='):
            return line.split('=', 1)[1].strip()
    raise ValueError(f'{ini} names no Version')


def launch_options(
    *,
    config: Optional[Dict[str, Any]] = None,
    os: Optional[ListOrString] = None,
    block_images: Optional[bool] = None,
    block_webrtc: Optional[bool] = None,
    block_webgl: Optional[bool] = None,
    disable_coop: Optional[bool] = None,
    webgl_config: Optional[Tuple[str, str]] = None,
    geoip: Optional[Union[str, bool]] = None,
    geoip_db: Optional[str] = None,
    humanize: Optional[Union[bool, float]] = None,
    locale: Optional[Union[str, List[str]]] = None,
    addons: Optional[List[str]] = None,
    fonts: Optional[List[str]] = None,
    custom_fonts_only: Optional[bool] = None,
    exclude_addons: Optional[List[DefaultAddons]] = None,
    screen: Optional[Screen] = None,
    window: Optional[Tuple[int, int]] = None,
    fingerprint: Optional[Dict[str, Any]] = None,
    fingerprint_preset: Optional[Union[bool, Dict[str, Any]]] = None,
    ff_version: Optional[int] = None,
    headless: Optional[bool] = None,
    main_world_eval: Optional[bool] = None,
    allow_addon_new_tab: Optional[bool] = None,
    executable_path: Optional[Union[str, Path]] = None,
    browser: Optional[str] = None,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    proxy: Optional[Dict[str, str]] = None,
    enable_cache: Optional[bool] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, Union[str, float, bool]]] = None,
    i_know_what_im_doing: Optional[bool] = None,
    debug: Optional[bool] = None,
    virtual_display: Optional[str] = None,
    pin_cpu_cores: Optional[bool] = None,
    canvas_noise: Optional[bool] = None,
    **launch_options: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Launches a new browser instance for Camoufox.
    Accepts all Playwright Firefox launch options, along with the following:

    Parameters:
        config (Optional[Dict[str, Any]]):
            Camoufox properties to use. (read https://github.com/daijro/camoufox/blob/main/README.md)
        os (Optional[ListOrString]):
            Operating system to use for the fingerprint generation.
            Can be "windows", "macos", "linux", or a list to randomly choose from.
            Default: ["windows", "macos", "linux"]
        block_images (Optional[bool]):
            Whether to block all images.
        block_webrtc (Optional[bool]):
            Whether to block WebRTC entirely.
        block_webgl (Optional[bool]):
            Whether to block WebGL. To prevent leaks, only use this for special cases.
        disable_coop (Optional[bool]):
            Disables the Cross-Origin-Opener-Policy, allowing elements in cross-origin iframes,
            such as the Turnstile checkbox, to be clicked.
        geoip (Optional[Union[str, bool]]):
            Calculate longitude, latitude, timezone, country, & locale based on the IP address.
            Pass the target IP address to use, or `True` to find the IP address automatically.
        geoip_db (Optional[str]):
            Name of the GeoIP database to use (e.g., "GeoIP AIO by daijro").
            If not specified, uses the one chosen with `camoufox set --geoip`, or the default.
        humanize (Optional[Union[bool, float]]):
            Humanize the cursor movement.
            Takes either `True`, or the MAX duration in seconds of the cursor movement.
            The cursor typically takes up to 1.5 seconds to move across the window.
        locale (Optional[Union[str, List[str]]]):
            Locale(s) to use in Camoufox. The first listed locale will be used for the Intl API.
        addons (Optional[List[str]]):
            List of Firefox addons to use.
        fonts (Optional[List[str]]):
            Fonts to load into Camoufox (in addition to the default fonts for the target `os`).
            Takes a list of font family names that are installed on the system.
        custom_fonts_only (Optional[bool]):
            If enabled, OS-specific system fonts will be not be passed to Camoufox.
        exclude_addons (Optional[List[DefaultAddons]]):
            Default addons to exclude. Passed as a list of camoufox.DefaultAddons enums.
        screen (Optional[Screen]):
            Constrains the screen dimensions of the generated fingerprint.
            Takes a camoufox.fingerprints.Screen instance.
        window (Optional[Tuple[int, int]]):
            Set a fixed window size instead of generating a random one
        fingerprint (Optional[Fingerprint]):
            Use a custom fpgen fingerprint. Note: Not all values will be implemented.
            If not provided, a random fingerprint will be generated based on the provided
            `os` & `screen` constraints.
        fingerprint_preset (Optional[Union[bool, Dict[str, Any]]]):
            Opt into using real fingerprint presets instead of fpgen.
            Pass `True` to use a random bundled preset, or pass a preset dict directly.
            By default (None), fpgen generates a unique fingerprint.
        ff_version (Optional[int]):
            Firefox version to use. Defaults to the current Camoufox version.
            To prevent leaks, only use this for special cases.
        headless (Optional[bool]):
            Whether to run the browser in headless mode. Defaults to False.
            Note: If you are running linux, passing headless='virtual' to Camoufox, AsyncCamoufox
            or launch_server will use Xvfb.
        main_world_eval (Optional[bool]):
            Whether to enable running scripts in the main world.
            To use this, prepend "mw:" to the script: page.evaluate("mw:" + script).
        allow_addon_new_tab (Optional[bool]):
            Whether to allow addon open new tabs. Defaults to False.
        executable_path (Optional[Union[str, Path]]):
            Custom Camoufox browser executable path.
        browser (Optional[str]):
            Select a specific installed browser version. Can be:
            - Repo/build like "official/beta.20"
            - Build alone like "beta.20"
            - Full version like "134.0.2-beta.20"
            The build must be installed; it is never downloaded.
            If not specified, uses the paired build. Raises ValueError with
            executable_path or CAMOUFOX_EXECUTABLE_PATH.
        firefox_user_prefs (Optional[Dict[str, Any]]):
            Firefox user preferences to set.
        proxy (Optional[Dict[str, str]]):
            Proxy to use for the browser.
            Note: If geoip is True, a request will be sent through this proxy to find the target IP.
        enable_cache (Optional[bool]):
            Cache previous pages, requests, etc (uses more memory).
        args (Optional[List[str]]):
            Arguments to pass to the browser.
        env (Optional[Dict[str, Union[str, float, bool]]]):
            Environment variables to set.
        debug (Optional[bool]):
            Prints the config being sent to Camoufox.
        virtual_display (Optional[str]):
            Virtual display number. Ex: ':99'. This is handled by Camoufox, AsyncCamoufox and launch_server.
        pin_cpu_cores (Optional[bool]):
            Pin the browser to navigator.hardwareConcurrency cores
            (Linux/Windows) so the fingerprint's own core count can be kept:
            a page timing N parallel workers then measures the number it was
            told. OFF by default -- it costs real CPU and serializes concurrent
            launches. Without it the host's own (snapped) count is reported,
            which is equally coherent, just less diverse.
        webgl_config (Optional[Tuple[str, str]]):
            Use a specific WebGL vendor/renderer pair. Passed as a tuple of (vendor, renderer).
            The pair must be one fpgen has recorded from Firefox on `os`
            (camoufox.webgl.firefox_gpus); any other raises ValueError.
        canvas_noise (Optional[bool]):
            Replace canvas and WebGL readback with random data, as
            privacy.resistFingerprinting does in LibreWolf, Tor Browser and
            Mullvad Browser. Stock Firefox does not, so it warns. By default
            (None) the identity on the host's OS claims the GPU the host
            renders with, uncovered; it is on whenever the identity claims
            another OS or another GPU (webgl_config, a preset's, or a host GPU
            fpgen never recorded), whose canvas would otherwise show the host.
        **launch_options (Dict[str, Any]):
            Additional Firefox launch options.
    """
    ensure_browser_profile_dir(env)

    # The launch fills these in, so it works on copies: a caller's mapping
    # reused for a second launch would otherwise carry the first identity's
    # values in, as if the caller had set them.
    config = dict(config or {})
    addons = list(addons or [])
    args = list(args or [])
    firefox_user_prefs = dict(firefox_user_prefs or {})

    # Set default values for optional arguments
    if headless is None:
        headless = False
    if custom_fonts_only is None:
        custom_fonts_only = False
    if i_know_what_im_doing is None:
        i_know_what_im_doing = False
    # Keep per-launch overrides isolated from the process environment and from
    # mappings supplied by callers. In particular, DISPLAY must not outlive the
    # virtual display that owns it.
    env = dict(environ) if env is None else dict(env)
    # CAMOUFOX_EXECUTABLE_PATH points every launch at a specific build without
    # threading the path through each call site; the CI runners set it for the
    # browser/tests/playwright/patches guards, which construct AsyncCamoufox directly.
    _env_executable = environ.get('CAMOUFOX_EXECUTABLE_PATH', '').strip()
    if browser:
        if executable_path or _env_executable:
            raise ValueError(
                f'browser={browser!r} selects an installed build, but '
                f'{"executable_path" if executable_path else "CAMOUFOX_EXECUTABLE_PATH"} '
                'names a binary too. Pass one of them.'
            )
        # A selected build is launched like a caller's own binary: its files
        # are read from beside it, and the paired build is neither used nor fetched.
        executable_path = selected_launch_path(browser)
    elif executable_path is None and _env_executable:
        executable_path = _env_executable
    if isinstance(executable_path, str):
        # Convert executable path to a Path object
        executable_path = Path(abspath(executable_path))

    # Handle virtual display
    if virtual_display:
        env['DISPLAY'] = virtual_display
        # Virtual display uses Xvfb (X11). If the host session forces Wayland via env vars,
        # GTK/Firefox may try Wayland and ignore DISPLAY, breaking Xvfb usage.
        env['GDK_BACKEND'] = 'x11'
        env.pop('WAYLAND_DISPLAY', None)
        env["MOZ_ENABLE_WAYLAND"] = "0"

    # Warn the user for manual config settings
    if not i_know_what_im_doing:
        warn_manual_config(config)

    # Snapshot which domains the USER set before fingerprint generation fills in
    # the rest. The post-generation fix-ups below must
    # only touch generated values, never override what the user passed.
    _user_set_navigator = is_domain_set(config, 'navigator.')
    _user_set_screen_window = is_domain_set(config, 'screen.', 'window.')
    _user_set_media_devices = is_domain_set(config, 'mediaDevices:')
    _user_set_fonts = bool(fonts) or is_domain_set(config, 'fonts')
    _user_set_voices = is_domain_set(config, 'voices')
    _user_set_dnt = 'navigator.doNotTrack' in config
    _user_set_gpc = 'navigator.globalPrivacyControl' in config
    _user_set_accept_encoding = 'headers.Accept-Encoding' in config
    _user_set_audio_seed = 'audio:seed' in config

    # The salt that makes every seeded draw belong to this identity (see
    # fingerprints.identity_salt): stable when the caller pinned the identity
    # -- a Fingerprint, a preset dict, or their own config naming the UA --
    # and fresh otherwise.
    if fingerprint is not None:
        _identity_salt = identity_salt(fingerprint)
    elif isinstance(fingerprint_preset, dict):
        _identity_salt = identity_salt(fingerprint_preset)
    elif 'navigator.userAgent' in config:
        _identity_salt = identity_salt(dict(config))
    else:
        _identity_salt = identity_salt()

    # Assert the target OS is valid
    if os:
        check_valid_os(os)

    # webgl_config requires OS to be set
    elif webgl_config:
        raise ValueError('OS must be set when using webgl_config')

    # Add the default addons
    add_default_addons(addons, exclude_addons)

    # Confirm all addon paths are valid
    if addons:
        confirm_paths(addons)
        config['addons'] = addons

    # Resolve the binary that will launch before reading its version:
    # launch_path() downloads the browser when none is installed, and the
    # identity has to match the Firefox that actually runs.
    browser_binary = str(executable_path) if executable_path else launch_path()
    warn_if_package_outdated()

    # Get the Firefox version
    if ff_version:
        ff_version_str = str(ff_version)
        LeakWarning.warn('ff_version', i_know_what_im_doing)
    else:
        ff_version_str = resolve_verstr(executable_path).split('.', 1)[0]

    # Generate a fingerprint
    _used_preset = False
    if fingerprint is not None:
        # User passed a custom fingerprint
        if not i_know_what_im_doing:
            check_custom_fingerprint(fingerprint)
    elif fingerprint_preset:
        # User opted into real fingerprint presets
        if isinstance(fingerprint_preset, dict):
            preset = fingerprint_preset
        else:
            preset = get_random_preset(os=os, ff_version=ff_version_str)
        if preset:
            merge_into(config, from_preset(preset, ff_version_str, salt=_identity_salt))
            _used_preset = True

    # Bound the geometry to the real display. The generator drops the bound when
    # nothing fits it, so it is re-applied after generation as well.
    # `headless` and "is there a display to probe" are separate questions: passing
    # `headless or has_display(env)` made a headful run on a real display look like a
    # headless one to get_screen_cons(), which then skipped the bound entirely.
    screen_cons = screen or (get_screen_cons(headless) if has_display(env) else None)

    if not _used_preset and fingerprint is None:
        # Default: synthetic generation via fpgen (infinite unique fingerprints)
        fingerprint = generate_fingerprint(
            screen=screen_cons,
            window=window,
            os=os,
        )

    if not _used_preset and fingerprint is not None:
        # Inject the generated fingerprint into the config
        merge_into(
            config,
            from_fpgen(fingerprint, ff_version_str),
        )

    target_os = get_target_os(config)

    # A preset whose screen is a phone viewport is not a real desktop device;
    # the floor is normally skipped for presets, on the assumption that a preset
    # IS a real machine, which 736x414 disproves.
    if not _user_set_screen_window and coherence.screen_is_implausible(config):
        coherence.repair_screen_orientation(config)
        raise_screen_to_modern_floor(config)

    # Correct fingerprint inconsistencies that leak as headless /
    # impossible-geometry tells, unless the user is driving these themselves.
    if not _user_set_navigator:
        fix_navigator_arch(config, target_os)
        fix_hardware_concurrency(config, can_pin=bool(pin_cpu_cores))
    if not _user_set_screen_window:
        # Lift netbook-era geometry to something current hardware reports,
        # before the display clamp below so a genuinely small real monitor
        # still wins (#729). Synthetic draws only: a preset is a real device,
        # internally consistent by construction, and two of the bundled v150
        # presets genuinely report sub-netbook screens (736x414, 960x540).
        # Rewriting those to 1366x768 would break the very coherence #729 is
        # about, and _user_set_screen_window is read before the preset merges
        # in, so it does not cover this.
        if not _used_preset:
            raise_screen_to_modern_floor(config)
        # Headful on a real monitor only: this bound exists so the window fits
        # the screen it is drawn on. headless has no window to overflow, and
        # headless='virtual' reaches here as headless=False (see async_api) with
        # a 1x1 Xvfb (virtdisplay.py) that is not a real screen.
        if headless is False and not virtual_display and screen_cons:
            clamp_screen_to_display(config, screen_cons.max_width, screen_cons.max_height)
        follow_baseline_protection(config, target_os)
        clamp_window_dimensions(config)
        clamp_window_position(config)

    # Deliberately NOT setting window.history.length. It used to be pinned to a
    # random 1-5 because browser.sessionhistory.max_entries=0 left the real
    # session history empty, so the honest value was 0 -- an impossible number,
    # since the HTML spec guarantees a browsing context always keeps its current
    # entry. browser/settings/camoufox.cfg now runs Firefox's stock max_entries, so the
    # real value starts at 1 and grows with each navigation.
    #
    # Pinning it on top of that is strictly worse than leaving it alone: the
    # value would no longer move across navigations, and a fresh tab would claim
    # a depth of, say, 4 while history.back() -- which reads the real session
    # history -- does nothing. Any page can check that pair. The property stays
    # in properties.json for callers who want to override it by hand.

    # Update fonts list
    if fonts:
        config['fonts'] = fonts

    if custom_fonts_only:
        firefox_user_prefs['gfx.bundled-fonts.activate'] = 0
        if fonts:
            LeakWarning.warn('custom_fonts_only')
        else:
            raise ValueError('No custom fonts were passed, but `custom_fonts_only` is enabled.')
    elif not _user_set_fonts or not config.get('fonts'):
        # Draw the font subset HERE, after every identity fix-up above, so the
        # seed sees the final UA/screen/cores/GPU: the same presented identity
        # always gets the same font list (#442/#765). A draw the fingerprint
        # generator made earlier from a partial config is replaced.
        os_name = OS_NAMES.get(target_os, 'macos')
        try:
            config['fonts'] = _generate_random_font_subset(
                os_name,
                seed=identity_seed(config, _identity_salt),
                # host's own OS on macOS/Windows: the real system fonts are used
                # (font-hijacker.patch keeps the bundle inactive), so only the
                # OS base is claimed
                native=(target_os in ('mac', 'win') and _host_os_key() == target_os),
            )
        except (OSError, ValueError) as e:
            FallbackWarning.warn(
                'Drawing the font list', f"every font fonts.json lists for {target_os}", e,
                config.get('navigator.userAgent'),
            )
            update_fonts(config, target_os)

    # Draw the identity's media devices (counts + OS-style labels/groups from
    # media-devices.json, seeded by the identity) unless the caller set any
    # mediaDevices: key. An empty enumerateDevices() list is a headless tell;
    # a wrong label after a grant is a spoof tell.
    if not _user_set_media_devices:
        set_media_devices_defaults(config, _identity_salt)

    # Scrollbars: a stock Firefox on a GNOME/KDE desktop and on macOS draws
    # overlay scrollbars (no layout gutter, scrollbar-width "auto"). On Windows it
    # follows the OS: Windows 11's default ("Always show scrollbars" off) is
    # overlay -- stock 152.0.4 on a Win11 laptop measures 0 px -- while Windows 10
    # draws classic 17 px ones. Headless Firefox reports the classic kind, and
    # upstream Playwright hid them outright, which a page can read back. Pin the
    # look-and-feel to the claimed OS so headless == headed == stock, and for
    # Windows to the version the identity's font draw presents
    # (WINDOWS_11_MARKER_FONTS): Win11 fonts with classic scrollbars
    # is a pair no real machine produces.
    if target_os == 'win':
        presented_fonts = config.get('fonts') or []
        windows_11 = not presented_fonts or any(
            font in presented_fonts for font in WINDOWS_11_MARKER_FONTS
        )
        firefox_user_prefs.setdefault('ui.useOverlayScrollbars', 1 if windows_11 else 0)
    else:
        firefox_user_prefs.setdefault('ui.useOverlayScrollbars', 1)

    # Per-character font fallback, LINUX ONLY. Gecko's GlobalFontFallback walks
    # the shared font list for a family whose charmap covers the character; in a
    # content process with async fallback on it hits the
    # `!family.IsFullyInitialized()` branch, schedules a cmap load and SKIPS the
    # family, so the first measurement of a character only one bundled family
    # provides returns the primary family's .notdef. Linux takes that path for
    # every fallback (gfxPlatformGtk::UseCmapsDuringSystemFallback is true), so
    # the font-hijacker fix that restored this on macOS cannot reach it here.
    # Measured 2026-09-15, 32px canvas `serif`, U+0870: .notdef 19.0 with async
    # on, a real glyph (9.25) with it off; stock Firefox resolves it.
    # macOS must NOT get this: it uses the platform (CoreText) fallback, where
    # forcing the synchronous scan changed the face picked for U+1E9E in Futura
    # (21.733 stock -> 27.267) -- measured on a stock Mac mini, 1/14 families
    # regressed. Windows is untested until a Windows build exists.
    if target_os == 'lin':
        firefox_user_prefs.setdefault('gfx.font_rendering.fallback.async', False)

    # Storage quota, from the host's own disk. A page reads the group limit
    # through navigator.storage.estimate().quota; see
    # _stock_profile_disk_capacity_kb for how Gecko derives it. Playwright's
    # profile is a throwaway directory under the system temp dir, which on a
    # tmpfs /tmp is a RAM-sized volume, so leaving Gecko to measure it reports a
    # disk this machine does not have. Pinning the limit instead -- camoufox.cfg
    # used to set 50 GiB, which is exactly nsRFPService::GetSpoofedStorageLimit()
    # -- reports 10 GiB on every host, including hosts whose real disk is far
    # smaller and whose stock Firefox therefore reports capacity / 10.
    _quota_limit_kb = _stock_profile_disk_capacity_kb()
    if _quota_limit_kb:
        firefox_user_prefs.setdefault(_QUOTA_FIXED_LIMIT_PREF, _quota_limit_kb)

    # Bundled fonts: on macOS and Windows the package's font bundle is
    # registered on top of the system fonts, and a bundled face of a family
    # the system also has (Papyrus, Helvetica, ...) wins the lookup with
    # metrics that differ from the real one (measured 2026-09-14 on a stock
    # Mac mini: bundled Papyrus 224.3 px vs the system's 247.3 px). When the
    # identity is the host's own OS the real system fonts ARE the right ones.
    # `gfx.bundled-fonts.activate` cannot do it from here (a `once` pref the
    # font list reads before profile prefs apply), so font-hijacker.patch
    # skips the activation itself whenever navigator.platform is the host's;
    # the font draw above claims only the OS base in that case (`native`).

    # navigator.doNotTrack and navigator.globalPrivacyControl are pref-backed: the
    # getters, the worker getters and the DNT / Sec-GPC headers all read the same
    # pref, so they are applied as prefs (daijro/camoufox#760). Stock Firefox 152
    # reports "unspecified" and false, so a generated value is dropped unless the
    # caller set it.
    #
    # screen.colorDepth is left as drawn: real macOS reports 30 and Windows /
    # Linux 24, and the CSS `color` feature follows the spoofed depth
    # (screen-spoofing.patch), so pinning it would only misreport macOS.

    if not _user_set_dnt:
        config.pop('navigator.doNotTrack', None)
    if not _user_set_gpc:
        config.pop('navigator.globalPrivacyControl', None)
    dnt = config.get('navigator.doNotTrack')
    firefox_user_prefs['privacy.donottrackheader.enabled'] = dnt is not None and str(dnt) == '1'
    gpc = config.get('navigator.globalPrivacyControl')
    firefox_user_prefs['privacy.globalprivacycontrol.enabled'] = bool(gpc) if gpc is not None else False

    # Accept-Encoding: stock Firefox advertises "gzip, deflate, br, zstd" over
    # https and only "gzip, deflate" over http; a forced header value is sent
    # on both (measured 2026-09-14: br/zstd on a plain-http echo). Firefox's
    # own value is already what the identity claims, so the generated header
    # is dropped unless the caller set it.
    if not _user_set_accept_encoding:
        config.pop('headers.Accept-Encoding', None)

    # The audio noise seed follows the identity: a returning "same device" must
    # reproduce its audio hash (#442/#765). Never 0 (0 disables the noise). A
    # preset draws its own random seed; it is replaced here too so a pinned
    # preset reproduces it, but a seed the caller set is kept. There is no
    # canvas seed: the browser adds no canvas noise (#528), and no glyph-spacing
    # noise either (ci/tribal-rules.yml: no-glyph-spacing-noise).
    if not _user_set_audio_seed:
        _ident = identity_seed(config, _identity_salt)
        config['audio:seed'] = ((_ident * 2654435761 + 97) & 0xFFFFFFFF) or 1

    # Set geolocation
    if geoip:
        geoip_allowed()  # Assert that geoip is allowed

        if geoip is True:
            # Find the user's IP address
            if proxy:
                geoip = public_ip(Proxy(**proxy).as_string())
            else:
                geoip = public_ip()

        # Spoof WebRTC if not blocked
        if not block_webrtc:
            if valid_ipv4(geoip):
                set_into(config, 'webrtc:ipv4', geoip)
                firefox_user_prefs['network.dns.disableIPv6'] = True
            elif valid_ipv6(geoip):
                set_into(config, 'webrtc:ipv6', geoip)

        geolocation = get_geolocation(geoip, geoip_db=geoip_db)
        geo_config = geolocation.as_config()
        for key, value in geo_config.items():
            if key in ('timezone', 'locale:language', 'locale:region', 'locale:script'):
                config.setdefault(key, value)
            else:
                config[key] = value

    # A page that receives a position without a prompt must also see
    # permissions.query({name: 'geolocation'}) report "granted" -- that is
    # what a real Firefox with a stored site grant does. The C++ auto-grant
    # alone delivers the fix while the Permissions API still says "prompt",
    # which is an incoherence a page can test (daijro/camoufox#769). The
    # allow-by-default pref is the same state a user creates by choosing
    # "Always allow", so both APIs agree without any per-site permission.
    if 'geolocation:latitude' in config and 'geolocation:longitude' in config:
        firefox_user_prefs.setdefault('permissions.default.geo', 1)

    # Raise a warning when a proxy is being used without spoofing geolocation.
    # This is a very bad idea; the warning cannot be ignored with i_know_what_im_doing.
    elif (
        proxy
        and 'localhost' not in proxy.get('server', '')
        and not is_domain_set(config, 'geolocation')
    ):
        LeakWarning.warn('proxy_without_geoip')

    # Set locale
    if locale:
        handle_locales(locale, config)

    # Select the browser's UI locale to match the Intl locale. Every
    # package bakes in Firefox's language packs as packaged locales
    # (browser/scripts/inject-locales.py); without this pref the browser stays en-US, so
    # a spoofed fr-FR localizes Intl/number/date formatting while
    # input.validationMessage and XML parse errors stay English -- a mix no real
    # Firefox produces (a Mozilla fr build localizes both). Gecko negotiates the
    # value against the packaged locales exactly as a localized build does
    # (fr-FR -> fr, pt-BR -> pt-BR), falling back to en-US. Always set: an EMPTY
    # value would follow the host OS locale now that more than en-US is packaged.
    if config.get('locale:language'):
        requested = '-'.join(
            part
            for part in (
                config['locale:language'],
                config.get('locale:script'),
                config.get('locale:region'),
            )
            if part
        )
    else:
        requested = 'en-US'
    firefox_user_prefs.setdefault('intl.locale.requested', requested)

    # Spoof the speech-synthesis voice list.
    #
    # This has to fail CLOSED. Firefox registers the host's speech-dispatcher /
    # SAPI / NSSpeech voices unless something stops it, and nsSynthVoiceRegistry
    # only stops it when Camoufox owns the list. Leaving `voices` unset -- which
    # the old `except Exception: pass` did on any generation failure -- exposed
    # every native voice on the box (14805 espeak-ng entries on a stock Linux
    # install) under a fingerprint claiming macOS or Windows: it both leaks the
    # real host OS and contradicts the rest of the profile (#731).
    #
    # Drawn after the locale is resolved (locale= or geoip): the Windows voice
    # list is the display language's pack, so an fr-FR identity has French
    # voices, not the en-US ones.
    if not _user_set_voices or 'voices' not in config:
        os_name_v = OS_NAMES.get(target_os, 'macos')
        voice_locale = config.get('navigator.language')
        if config.get('locale:language'):
            voice_locale = '-'.join(
                part for part in (config['locale:language'], config.get('locale:region')) if part
            )
        try:
            config['voices'] = _generate_random_voice_subset(
                os_name_v, voice_locale, seed=identity_seed(config, _identity_salt)
            )
        except (OSError, ValueError, KeyError) as e:
            # An empty list still blocks the host's voices (see below), so a
            # generation failure degrades to "no voices" rather than "all of
            # the host's".
            FallbackWarning.warn(
                'Drawing the speech voices', 'no speech voices', e, config.get('navigator.userAgent')
            )
            config['voices'] = []

    # Pin the block explicitly instead of relying on a non-empty list to imply
    # it, so an empty list -- or one whose entries the browser rejects as
    # malformed -- cannot fall through to the host's native voices. set_into
    # leaves an explicit caller value alone.
    set_into(config, 'voices:blockIfNotDefined', True)

    # Pass the humanize option
    if humanize:
        set_into(config, 'humanize', True)
        # bool is a subclass of int, but MaskConfig expects maxTime to be a
        # JSON number with a floating-point representation.
        if isinstance(humanize, (int, float)) and not isinstance(humanize, bool):
            set_into(config, 'humanize:maxTime', float(humanize))

    # Enable the main world context creation
    if main_world_eval:
        set_into(config, 'allowMainWorld', True)

    # Allow addon open new tabs
    if allow_addon_new_tab:
        set_into(config, 'allowAddonNewtab', True)

    # Set Firefox user preferences. Each toggle writes its pref on or off: a
    # persistent profile keeps a user.js pref in prefs.js after the launch that
    # set it, so a flag that only wrote when on stayed on for good.
    if block_images:
        LeakWarning.warn('block_images', i_know_what_im_doing)
    if disable_coop:
        LeakWarning.warn('disable_coop', i_know_what_im_doing)
    firefox_user_prefs.setdefault('permissions.default.image', 2 if block_images else 1)
    firefox_user_prefs.setdefault('media.peerconnection.enabled', not block_webrtc)
    firefox_user_prefs.setdefault('browser.tabs.remote.useCrossOriginOpenerPolicy', not disable_coop)
    # A persistent context takes its context options here.
    if launch_options.get('is_mobile'):
        LeakWarning.warn('is_mobile', i_know_what_im_doing)

    # Drop values the source supplied that this identity cannot keep, before the
    # WebGL pool below defers to them (a preset's own GPU pair wins over
    # sampling). Here, not earlier, because the check reads the core count and
    # the screen, which the host core count and the display clamp replace.
    coherence.drop_incoherent_source_values(config, target_os)

    cover_canvas, host = plan_rendering(
        target_os,
        canvas_noise,
        bool(webgl_config or (config.get('webGl:vendor') and config.get('webGl:renderer'))),
        bool(block_webgl),
        lambda: host_gpu(browser_binary, headless, env),
    )
    if cover_canvas:
        add_canvas_placeholder(firefox_user_prefs)
        LeakWarning.warn('canvas_noise', i_know_what_im_doing)

    if block_webgl:
        firefox_user_prefs['webgl.disabled'] = True
        LeakWarning.warn('block_webgl', i_know_what_im_doing)
    else:
        # A pair the caller named, or the preset's own GPU, keeps its name and
        # gets that device's recorded parameters. webgl_for_gpu raises for a GPU
        # fpgen has never seen: the caller asked for something that does not exist.
        if webgl_config:
            webgl_fp = webgl_for_gpu(target_os, *webgl_config, seed=identity_seed(config, _identity_salt))
        elif config.get('webGl:vendor') and config.get('webGl:renderer'):
            webgl_fp = webgl_for_gpu(
                target_os, config['webGl:vendor'], config['webGl:renderer'],
                seed=identity_seed(config, _identity_salt),
            )
        elif host:
            # Claim the GPU the canvas really renders on.
            webgl_fp = webgl_for_gpu(target_os, *host, seed=identity_seed(config, _identity_salt))
        else:
            # Synthetic path: keep the GPU coherent with the screen fpgen
            # already picked. Sampling the two independently yields pairs no
            # real machine ships -- a discrete desktop GPU behind a 1024x600
            # panel -- which consistency checks read as masking (#729).
            webgl_fp = sample_webgl_for_screen(
                target_os, config.get('screen.width'), config.get('screen.height'),
                seed=identity_seed(config, _identity_salt),
                cores=config.get('navigator.hardwareConcurrency'),
            )
        enable_webgl2 = webgl_fp.pop('webGl2Enabled')

        # Merge the WebGL fingerprint into the config
        merge_into(config, webgl_fp)
        # Set the WebGL preferences
        merge_into(
            firefox_user_prefs,
            {
                'webgl.enable-webgl2': enable_webgl2,
                'webgl.force-enabled': True,
            },
        )

    # Every identity passes the whole-identity checks, whatever built it: a
    # generated fingerprint, a bundled preset, or a config the caller wrote.
    # The pools are sampled independently -- navigator and screen from the
    # generator, GPU from fpgen's WebGL records, fonts and voices from their own
    # catalogues -- so a machine that never existed can be assembled from parts
    # that are each fine on their own. See coherence.py.
    _incoherent = coherence.apply(config, target_os)
    if _incoherent and debug:
        for _violation in _incoherent:
            print(f'Incoherent identity ({_violation.rule}): {_violation.detail}')

    set_webgpu(firefox_user_prefs, target_os, (config.get('webGl:vendor'), config.get('webGl:renderer')), host)

    # Cache previous pages, requests, etc (uses more memory)
    if enable_cache:
        merge_into(firefox_user_prefs, CACHE_PREFS)

    # Print the config if debug is enabled
    if debug:
        print('[DEBUG] Config:')
        pprint(config)

    # Validate the config
    warn_if_executable_predates_playwright(executable_path)
    validate_config(config, path=executable_path)

    # Prepare environment variables to pass to Camoufox
    env_vars = {
        **get_env_vars(config, target_os, path=executable_path),
        **get_pref_env_vars(firefox_user_prefs),
        **env,
    }
    result = {
        "executable_path": browser_binary,
        "args": args,
        "env": env_vars,
        "firefox_user_prefs": firefox_user_prefs,
        "headless": headless,
        **(launch_options if launch_options is not None else {}),
    }
    # Only include proxy if it's not None (Playwright 1.55+ validates this)
    # https://github.com/coryking/camoufox/commit/1336e8e509e8c12a896a09d9ee51f131f739f106
    # Thanks @coryking
    if proxy is not None:
        result["proxy"] = proxy

    return result
