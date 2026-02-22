import importlib.util
import os
import sys
import types
from typing import Any, Dict

def _mock_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod

def _load_module_from_path(module_name: str, file_path: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load spec for {module_name} from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod

PYTHONLIB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../pythonlib"))
CAMOUFOX_PKG_DIR = os.path.join(PYTHONLIB_DIR, "camoufox")

# Ensure pythonlib is on sys.path so relative imports inside loaded modules can resolve.
if PYTHONLIB_DIR not in sys.path:
    sys.path.append(PYTHONLIB_DIR)

# Create a stub 'camoufox' package so we can load submodules WITHOUT executing camoufox/__init__.py.
camoufox_pkg = _mock_module("camoufox")
camoufox_pkg.__path__ = [CAMOUFOX_PKG_DIR]

# Minimal stubs for third-party modules imported at module-import time.
numpy_mod = _mock_module("numpy")
numpy_mod.unique = lambda x: list(dict.fromkeys(x))
numpy_mod.array = lambda x, dtype=None: x
numpy_mod.float64 = float

orjson_mod = _mock_module("orjson")
orjson_mod.dumps = lambda obj: ("{}" if obj is None else str(obj)).encode("utf-8")
orjson_mod.loads = lambda b: b
orjson_mod.JSONEncodeError = Exception

screeninfo_mod = _mock_module("screeninfo")
screeninfo_mod.get_monitors = lambda: []

typing_ext_mod = _mock_module("typing_extensions")
typing_ext_mod.TypeAlias = Any

# Minimal third-party stubs used by the modules under test.
ua_parser = _mock_module("ua_parser")
class _MockUserAgentParser:
    @staticmethod
    def ParseUserAgent(_: str):
        return {"family": "Firefox"}
    @staticmethod
    def ParseOS(_: str):
        return {"family": "Windows"}
ua_parser.user_agent_parser = _MockUserAgentParser

browserforge = _mock_module("browserforge")
browserforge_fps = _mock_module("browserforge.fingerprints")
class _MockFingerprint:  # pragma: no cover
    pass
class _MockScreen:  # pragma: no cover
    pass
class _MockFingerprintGenerator:  # pragma: no cover
    def __init__(self, **_: Any):
        pass
    def generate(self, **_: Any):
        return _MockFingerprint()
class _MockScreenFingerprint:  # pragma: no cover
    pass
browserforge_fps.Fingerprint = _MockFingerprint
browserforge_fps.Screen = _MockScreen
browserforge_fps.FingerprintGenerator = _MockFingerprintGenerator
browserforge_fps.ScreenFingerprint = _MockScreenFingerprint

# Stub camoufox.pkgman.load_yaml so fingerprints.py can load browserforge.yml mappings.
pkgman = _mock_module("camoufox.pkgman")
def _mock_load_yaml(_: str) -> Dict[str, Any]:
    return {
        "navigator": {
            "userAgent": "navigator.userAgent",
            "doNotTrack": "navigator.doNotTrack",
            "appCodeName": "navigator.appCodeName",
            "appName": "navigator.appName",
            "appVersion": "navigator.appVersion",
            "oscpu": "navigator.oscpu",
            "platform": "navigator.platform",
            "hardwareConcurrency": "navigator.hardwareConcurrency",
            "product": "navigator.product",
            "maxTouchPoints": "navigator.maxTouchPoints",
            "extraProperties": {
                "globalPrivacyControl": "navigator.globalPrivacyControl",
            },
        },
        "screen": {
            "availLeft": "screen.availLeft",
            "availTop": "screen.availTop",
            "availWidth": "screen.availWidth",
            "availHeight": "screen.availHeight",
            "height": "screen.height",
            "width": "screen.width",
            "colorDepth": "screen.colorDepth",
            "pixelDepth": "screen.pixelDepth",
            "pageXOffset": "screen.pageXOffset",
            "pageYOffset": "screen.pageYOffset",
            "outerHeight": "window.outerHeight",
            "outerWidth": "window.outerWidth",
            "innerHeight": "window.innerHeight",
            "innerWidth": "window.innerWidth",
            "screenX": "window.screenX",
            "screenY": "window.screenY",
        },
        "headers": {
            "Accept-Encoding": "headers.Accept-Encoding",
        },
        "battery": {
            "charging": "battery:charging",
            "chargingTime": "battery:chargingTime",
            "dischargingTime": "battery:dischargingTime",
        },
        "webgl": {
            "renderer": "webGl:renderer",
            "vendor": "webGl:vendor"
        },
        "timezone": "timezone",
    }
pkgman.load_yaml = _mock_load_yaml

# Stub camoufox.exceptions + camoufox.warnings for check_custom_fingerprint.
exceptions_mod = _mock_module("camoufox.exceptions")
class NonFirefoxFingerprint(Exception):
    pass
exceptions_mod.NonFirefoxFingerprint = NonFirefoxFingerprint

warnings_mod = _mock_module("camoufox.warnings")
class LeakWarning:  # pragma: no cover
    @staticmethod
    def warn(*_: Any, **__: Any):
        return
warnings_mod.LeakWarning = LeakWarning

# Stub the rest of camoufox.* imports used by utils.py at import time.
addons_mod = _mock_module("camoufox.addons")
class DefaultAddons:  # pragma: no cover
    pass
def add_default_addons(*_: Any, **__: Any):
    return
def confirm_paths(*_: Any, **__: Any):
    return
addons_mod.DefaultAddons = DefaultAddons
addons_mod.add_default_addons = add_default_addons
addons_mod.confirm_paths = confirm_paths

exceptions_mod.InvalidOS = type("InvalidOS", (Exception,), {})
exceptions_mod.InvalidPropertyType = type("InvalidPropertyType", (Exception,), {})
exceptions_mod.UnknownProperty = type("UnknownProperty", (Exception,), {})

ip_mod = _mock_module("camoufox.ip")
class Proxy:  # pragma: no cover
    def __init__(self, **_: Any):
        pass
    def as_string(self) -> str:
        return ""
def public_ip(*_: Any, **__: Any) -> str:
    return "127.0.0.1"
def valid_ipv4(_: str) -> bool:
    return True
def valid_ipv6(_: str) -> bool:
    return False
ip_mod.Proxy = Proxy
ip_mod.public_ip = public_ip
ip_mod.valid_ipv4 = valid_ipv4
ip_mod.valid_ipv6 = valid_ipv6

locale_mod = _mock_module("camoufox.locale")
def geoip_allowed() -> None:
    return
def get_geolocation(*_: Any, **__: Any):
    class _Geo:
        def as_config(self) -> Dict[str, Any]:
            return {}
    return _Geo()
def handle_locales(*_: Any, **__: Any) -> None:
    return
locale_mod.geoip_allowed = geoip_allowed
locale_mod.get_geolocation = get_geolocation
locale_mod.handle_locales = handle_locales

pkgman.OS_NAME = "win"
pkgman.get_path = lambda x: x
pkgman.installed_verstr = lambda: "120.0-1"
pkgman.launch_path = lambda: "camoufox.exe"

virtdisplay_mod = _mock_module("camoufox.virtdisplay")
class VirtualDisplay:  # pragma: no cover
    def __init__(self, **_: Any):
        pass
    def get(self) -> str:
        return ":0"
virtdisplay_mod.VirtualDisplay = VirtualDisplay

webgl_mod = _mock_module("camoufox.webgl")
webgl_mod.sample_webgl = lambda *_args, **_kwargs: {"webGl2Enabled": False}

# Load the modules under test WITHOUT importing camoufox/__init__.py.
fingerprints_mod = _load_module_from_path(
    "camoufox.fingerprints", os.path.join(CAMOUFOX_PKG_DIR, "fingerprints.py")
)
utils_mod = _load_module_from_path(
    "camoufox.utils", os.path.join(CAMOUFOX_PKG_DIR, "utils.py")
)

from_browserforge = fingerprints_mod.from_browserforge
check_custom_fingerprint = utils_mod.check_custom_fingerprint

def test_fingerprint_dict_support():
    print("Testing dictionary support in fingerprint handling...")
    
    # Mock fingerprint dictionary (simulating loaded JSON)
    mock_fingerprint = {
        "navigator": {
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "appVersion": "5.0 (Windows)",
            "platform": "Win32",
            "hardwareConcurrency": 16,
            "language": "en-US",
            "languages": ["en-US", "en"],
            "doNotTrack": "1",
            "appCodeName": "Mozilla",
            "appName": "Netscape",
            "oscpu": "Windows NT 10.0; Win64; x64",
            "product": "Gecko",
            "maxTouchPoints": 0,
            "globalPrivacyControl": True
        },
        "screen": {
            "availHeight": 1040,
            "availWidth": 1920,
            "availTop": 0,
            "availLeft": 0,
            "colorDepth": 24,
            "pixelDepth": 24,
            "height": 1080,
            "width": 1920,
            "outerHeight": 900,
            "outerWidth": 1600,
            "devicePixelRatio": 1,
            "pageXOffset": 0,
            "pageYOffset": 0,
            "screenX": 0,
            "screenY": 0
        },
        "headers": {
             "Accept-Encoding": "gzip, deflate, br"
        },
        "battery": {
            "charging": True,
            "chargingTime": 0,
            "dischargingTime": "Infinity",
            "level": 1
        },
        "webgl": {
             "vendor": "Google Inc. (NVIDIA)",
             "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"
        },
        "timezone": "America/New_York",
        "videoCard": {
             "vendor": "Google Inc. (NVIDIA)",
             "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"
        }
    }

    # Test check_custom_fingerprint
    try:
        check_custom_fingerprint(mock_fingerprint)
        print("PASS: check_custom_fingerprint accepted valid dict.")
    except Exception as e:
        print(f"FAIL: check_custom_fingerprint raised exception: {e}")
        # return # Continue testing

    # Test from_browserforge
    try:
        config = from_browserforge(mock_fingerprint, ff_version="120")
        print("PASS: from_browserforge processed dict.")
        
        # Verify keys
        expected_keys = [
            'navigator.userAgent',
            'navigator.platform',
            'screen.width',
            'screen.height',
            'window.screenX',
            'window.screenY',
            'webGl:renderer',
            'webGl:vendor',
            'timezone'
        ]
        
        for key in expected_keys:
            if key in config:
                print(f"  Verified key present: {key} = {config[key]}")
            else:
                print(f"FAIL: Missing key {key} in generated config")
                
        # Verify version replacement in UA
        expected_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
        if config['navigator.userAgent'] == expected_ua:
             print("PASS: UserAgent version substitution worked.")
        else:
             print(f"FAIL: UserAgent version substitution failed.\nExpected: {expected_ua}\nGot: {config['navigator.userAgent']}")

    except Exception as e:
        print(f"FAIL: from_browserforge raised exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_fingerprint_dict_support()
