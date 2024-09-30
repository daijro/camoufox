import os
import sys
from os import environ
from random import randrange
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast

import numpy as np
import orjson
from browserforge.fingerprints import Fingerprint, Screen
from screeninfo import get_monitors
from typing_extensions import TypeAlias
from ua_parser import user_agent_parser

from .addons import (
    DefaultAddons,
    confirm_paths,
    get_debug_port,
    threaded_try_load_addons,
)
from .exceptions import InvalidPropertyType, UnknownProperty
from .fingerprints import from_browserforge, generate_fingerprint
from .ip import Proxy, public_ip, valid_ipv4, valid_ipv6
from .locale import geoip_allowed, get_geolocation, normalize_locale
from .pkgman import OS_NAME, get_path, installed_verstr
from .xpi_dl import add_default_addons

LAUNCH_FILE = {
    'win': 'camoufox.exe',
    'lin': 'camoufox-bin',
    'mac': '../MacOS/camoufox',
}

ListOrString: TypeAlias = Union[Tuple[str, ...], List[str], str]


def get_env_vars(
    config_map: Dict[str, str], user_agent_os: str
) -> Dict[str, Union[str, float, bool]]:
    """
    Gets a dictionary of environment variables for Camoufox.
    """
    env_vars: Dict[str, Union[str, float, bool]] = {}
    try:
        updated_config_data = orjson.dumps(config_map)
    except orjson.JSONEncodeError as e:
        print(f"Error updating config: {e}")
        sys.exit(1)

    # Split the config into chunks
    chunk_size = 2047 if OS_NAME == 'win' else 32767
    config_str = updated_config_data.decode('utf-8')

    for i in range(0, len(config_str), chunk_size):
        chunk = config_str[i : i + chunk_size]
        env_name = f"CAMOU_CONFIG_{(i // chunk_size) + 1}"
        try:
            env_vars[env_name] = chunk
        except Exception as e:
            print(f"Error setting {env_name}: {e}")
            sys.exit(1)

    if OS_NAME == 'lin':
        fontconfig_path = get_path(os.path.join("fontconfig", user_agent_os))
        env_vars['FONTCONFIG_PATH'] = fontconfig_path

    return env_vars


def _load_properties() -> Dict[str, str]:
    """
    Loads the properties.json file.
    """
    prop_file = get_path("properties.json")
    with open(prop_file, "rb") as f:
        prop_dict = orjson.loads(f.read())

    return {prop['property']: prop['type'] for prop in prop_dict}


def validate_config(config_map: Dict[str, str]) -> None:
    """
    Validates the config map.
    """
    property_types = _load_properties()

    for key, value in config_map.items():
        expected_type = property_types.get(key)
        if not expected_type:
            raise UnknownProperty(f"Unknown property {key} in config")

        if not validate_type(value, expected_type):
            raise InvalidPropertyType(
                f"Invalid type for property {key}. Expected {expected_type}, got {type(value).__name__}"
            )


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
    else:
        return False


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
    """
    if headless is False:
        return None  # Skip if headless
    try:
        monitors = get_monitors()
    except Exception:
        return None  # Skip if there's an error getting the monitors
    if not monitors:
        return None  # Skip if there are no monitors

    # Use the dimensions from the monitor with greatest screen real estate
    monitor = max(monitors, key=lambda m: m.width * m.height)
    # Add 25% buffer
    return Screen(max_width=int(monitor.width * 1.25), max_height=int(monitor.height * 1.25))


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


def get_launch_options(
    *,
    config: Optional[Dict[str, Any]] = None,
    addons: Optional[List[str]] = None,
    fingerprint: Optional[Fingerprint] = None,
    exclude_addons: Optional[List[DefaultAddons]] = None,
    screen: Optional[Screen] = None,
    geoip: Optional[Union[str, bool]] = None,
    locale: Optional[str] = None,
    os: Optional[ListOrString] = None,
    fonts: Optional[List[str]] = None,
    args: Optional[List[str]] = None,
    executable_path: Optional[str] = None,
    env: Optional[Dict[str, Union[str, float, bool]]] = None,
    block_images: Optional[bool] = None,
    block_webrtc: Optional[bool] = None,
    allow_webgl: Optional[bool] = None,
    proxy: Optional[Dict[str, str]] = None,
    ff_version: Optional[int] = None,
    headless: Optional[bool] = None,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    launch_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Builds the launch options for the Camoufox browser.
    """
    # Build the config
    if config is None:
        config = {}

    if addons is None:
        addons = []
    if args is None:
        args = []
    if firefox_user_prefs is None:
        firefox_user_prefs = {}

    # Add the default addons
    add_default_addons(addons, exclude_addons)

    # Confirm all addon paths are valid
    if addons:
        confirm_paths(addons)

    # Get the Firefox version
    if ff_version:
        ff_version_str = str(ff_version)
    else:
        ff_version_str = installed_verstr().split('.', 1)[0]

    # Inject a unique Firefox fingerprint
    if fingerprint is None:
        fingerprint = generate_fingerprint(
            screen=screen or get_screen_cons(headless),
            os=os,
        )
    merge_into(
        config,
        from_browserforge(fingerprint, ff_version_str),
    )

    target_os = get_target_os(config)

    # Set a random window.history.length
    set_into(config, 'window.history.length', randrange(1, 6))  # nosec

    # Update fonts list
    if fonts:
        config['fonts'] = fonts
    update_fonts(config, target_os)

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

        geolocation = get_geolocation(geoip)
        config.update(geolocation.as_config())

    # Set locale
    if locale:
        parsed_locale = normalize_locale(locale)
        config.update(parsed_locale.as_config())

    # Validate the config
    validate_config(config)

    # Set Firefox user preferences
    if block_images:
        firefox_user_prefs['permissions.default.image'] = 2
    if block_webrtc:
        firefox_user_prefs['media.peerconnection.enabled'] = False
    if allow_webgl:
        firefox_user_prefs['webgl.disabled'] = False

    # Launch
    threaded_try_load_addons(get_debug_port(args), addons)
    env_vars = {
        **get_env_vars(config, target_os),
        **(cast(Dict[str, Union[str, float, bool]], environ) if env is None else env),
    }
    return {
        "executable_path": executable_path or get_path(LAUNCH_FILE[OS_NAME]),
        "args": args,
        "env": env_vars,
        "firefox_user_prefs": firefox_user_prefs,
        "proxy": proxy,
        "headless": headless,
        **(launch_options if launch_options is not None else {}),
    }
