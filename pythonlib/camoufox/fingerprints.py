import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from random import choice, randint, randrange
from typing import Any, Dict, List, Optional, Tuple

from browserforge.fingerprints import (
    Fingerprint,
    FingerprintGenerator,
    ScreenFingerprint,
)

from camoufox.pkgman import load_yaml

# Load the browserforge.yaml file
BROWSERFORGE_DATA = load_yaml('browserforge.yml')

FP_GENERATOR = FingerprintGenerator(browser='firefox', os=('linux', 'macos', 'windows'))

# Bundled real fingerprint presets
PRESETS_FILE = Path(__file__).parent / 'fingerprint-presets.json'
_PRESETS_CACHE: Optional[Dict] = None


def load_presets() -> Optional[Dict]:
    """Load bundled fingerprint presets from JSON file."""
    global _PRESETS_CACHE
    if _PRESETS_CACHE is not None:
        return _PRESETS_CACHE
    if not PRESETS_FILE.exists():
        return None
    with open(PRESETS_FILE) as f:
        _PRESETS_CACHE = json.load(f)
    return _PRESETS_CACHE


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
) -> Optional[Dict]:
    """
    Get a random preset for the given OS.
    Returns None if no presets are available.
    """
    presets = load_presets()
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


def from_preset(preset: Dict, ff_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Convert a real fingerprint preset to CAMOU_CONFIG format.
    """
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
    if nav.get('language'):
        config['navigator.language'] = nav['language']
    if nav.get('languages'):
        config['navigator.languages'] = nav['languages']
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

    # Generate unique random seeds per launch (1 to 2^32-1, excluding 0 which is a no-op in C++)
    config['fonts:spacing_seed'] = randint(1, 4_294_967_295)  # nosec
    config['audio:seed'] = randint(1, 4_294_967_295)  # nosec
    config['canvas:seed'] = randint(1, 4_294_967_295)  # nosec

    if preset.get('timezone'):
        config['timezone'] = preset['timezone']
    if preset.get('fonts'):
        config['fonts'] = preset['fonts']
    if preset.get('speechVoices'):
        config['voices'] = preset['speechVoices']

    return config


def _build_init_script(values: Dict[str, Any]) -> str:
    """
    Builds the JavaScript init script that calls per-context window.setXxx() functions.
    These functions self-destruct after first call, so they must run via addInitScript.
    """
    import json as _json

    lines = ['(function(v) {', '  var w = window;']

    setters = [
        ('fontSpacingSeed', 'setFontSpacingSeed', '{val}'),
        ('audioFingerprintSeed', 'setAudioFingerprintSeed', '{val}'),
        ('canvasSeed', 'setCanvasSeed', '{val}'),
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

    # Timezone (always call to trigger self-destruct)
    tz = values.get('timezone')
    if tz:
        lines.append(
            f'  if (typeof w.setTimezone === "function") w.setTimezone({_json.dumps(tz)});'
        )
    else:
        lines.append(
            '  if (typeof w.setTimezone === "function") w.setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone);'
        )

    # WebRTC IP
    ip = values.get('webrtcIP')
    if ip:
        lines.append(
            f'  if (typeof w.setWebRTCIPv4 === "function") w.setWebRTCIPv4({_json.dumps(ip)});'
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

    # Speech voices (comma-separated)
    voices = values.get('speechVoices')
    if voices and len(voices) > 0:
        joined = ','.join(voices)
        lines.append(
            f'  if (typeof w.setSpeechVoices === "function") w.setSpeechVoices({_json.dumps(joined)});'
        )

    lines.append('})();')
    return '\n'.join(lines)


def generate_context_fingerprint(
    preset: Optional[Dict] = None,
    os: Optional[str] = None,
    ff_version: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate fingerprint values for a single per-context identity.
    Returns a dict with init_script (JS string) and context_options (Playwright options).

    If no preset is provided, picks a random one from bundled presets.
    Falls back to BrowserForge if no presets available.
    """
    if preset is None:
        preset = get_random_preset(os=os)

    if preset is None:
        # No presets available - cannot generate per-context fingerprint without one
        raise ValueError(
            'No fingerprint presets available. '
            'Ensure fingerprint-presets.json exists in the camoufox package.'
        )

    config = from_preset(preset, ff_version)

    nav = preset.get('navigator', {})
    screen = preset.get('screen', {})
    webgl = preset.get('webgl', {})

    # Build the values dict for the init script
    init_values: Dict[str, Any] = {
        'fontSpacingSeed': config.get('fonts:spacing_seed'),
        'audioFingerprintSeed': config.get('audio:seed'),
        'canvasSeed': config.get('canvas:seed'),
        'navigatorPlatform': nav.get('platform'),
        'navigatorOscpu': nav.get('oscpu'),
        'navigatorUserAgent': config.get('navigator.userAgent'),
        'hardwareConcurrency': nav.get('hardwareConcurrency'),
        'webglVendor': webgl.get('unmaskedVendor'),
        'webglRenderer': webgl.get('unmaskedRenderer'),
        'screenWidth': screen.get('width'),
        'screenHeight': screen.get('height'),
        'screenColorDepth': screen.get('colorDepth'),
        'timezone': preset.get('timezone'),
        'fontList': preset.get('fonts'),
        'speechVoices': preset.get('speechVoices'),
    }

    init_script = _build_init_script(init_values)

    # Playwright context options that must be set at context creation
    context_options: Dict[str, Any] = {}
    ua = config.get('navigator.userAgent')
    if ua:
        context_options['user_agent'] = ua
    if screen.get('width') and screen.get('height'):
        context_options['viewport'] = {
            'width': screen['width'],
            'height': screen['height'],
        }
    if screen.get('devicePixelRatio'):
        context_options['device_scale_factor'] = screen['devicePixelRatio']
    lang = nav.get('language')
    if lang:
        context_options['locale'] = lang
    tz = preset.get('timezone')
    if tz:
        context_options['timezone_id'] = tz

    return {
        'init_script': init_script,
        'context_options': context_options,
        'config': config,
        'preset': preset,
    }


@dataclass
class ExtendedScreen(ScreenFingerprint):
    """
    An extended version of Browserforge's ScreenFingerprint class
    """

    screenY: Optional[int] = None


def _cast_to_properties(
    camoufox_data: Dict[str, Any],
    cast_enum: Dict[str, Any],
    bf_dict: Dict[str, Any],
    ff_version: Optional[str] = None,
) -> None:
    """
    Casts Browserforge fingerprints to Camoufox config properties.
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
        # Fix values that are out of bounds
        if type_key.startswith("screen.") and isinstance(data, int) and data < 0:
            data = 0
        # Replace the Firefox versions with ff_version
        if ff_version and isinstance(data, str):
            data = re.sub(r'(?<!\d)(1[0-9]{2})(\.0)(?!\d)', rf'{ff_version}\2', data)
        camoufox_data[type_key] = data


def handle_screenXY(camoufox_data: Dict[str, Any], fp_screen: ScreenFingerprint) -> None:
    """
    Helper method to set window.screenY based on Browserforge's screenX value.
    """
    # Skip if manually provided
    if 'window.screenY' in camoufox_data:
        return
    # Default screenX to 0 if not provided
    screenX = fp_screen.screenX
    if not screenX:
        camoufox_data['window.screenX'] = 0
        camoufox_data['window.screenY'] = 0
        return

    # If screenX is within [-50, 50], use the same value for screenY
    if screenX in range(-50, 51):
        camoufox_data['window.screenY'] = screenX
        return

    # Browserforge thinks the browser is windowed. # Randomly generate a screenY value.
    screenY = fp_screen.availHeight - fp_screen.outerHeight
    if screenY == 0:
        camoufox_data['window.screenY'] = 0
    elif screenY > 0:
        camoufox_data['window.screenY'] = randrange(0, screenY)  # nosec
    else:
        camoufox_data['window.screenY'] = randrange(screenY, 0)  # nosec


def from_browserforge(fingerprint: Fingerprint, ff_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Converts a Browserforge fingerprint to a Camoufox config.
    """
    camoufox_data: Dict[str, Any] = {}
    _cast_to_properties(
        camoufox_data,
        cast_enum=BROWSERFORGE_DATA,
        bf_dict=asdict(fingerprint),
        ff_version=ff_version,
    )
    handle_screenXY(camoufox_data, fingerprint.screen)

    return camoufox_data


def handle_window_size(fp: Fingerprint, outer_width: int, outer_height: int) -> None:
    """
    Helper method to set a custom outer window size, and center it in the screen
    """
    # Cast the screen to an ExtendedScreen
    fp.screen = ExtendedScreen(**asdict(fp.screen))
    sc = fp.screen

    # Center the window on the screen
    sc.screenX += (sc.width - outer_width) // 2
    sc.screenY = (sc.height - outer_height) // 2

    # Update inner dimensions if set
    if sc.innerWidth:
        sc.innerWidth = max(outer_width - sc.outerWidth + sc.innerWidth, 0)
    if sc.innerHeight:
        sc.innerHeight = max(outer_height - sc.outerHeight + sc.innerHeight, 0)

    # Set outer dimensions
    sc.outerWidth = outer_width
    sc.outerHeight = outer_height


def generate_fingerprint(window: Optional[Tuple[int, int]] = None, **config) -> Fingerprint:
    """
    Generates a Firefox fingerprint with Browserforge.
    """
    if window:  # User-specified outer window size
        fingerprint = FP_GENERATOR.generate(**config)
        handle_window_size(fingerprint, *window)
        return fingerprint
    return FP_GENERATOR.generate(**config)


if __name__ == "__main__":
    from pprint import pprint

    fp = generate_fingerprint()
    pprint(from_browserforge(fp))
