import os
import sys
from os import environ
from pprint import pprint
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
from .exceptions import (
    InvalidOS,
    InvalidPropertyType,
    NonFirefoxFingerprint,
    UnknownProperty,
)
from .fingerprints import from_browserforge, generate_fingerprint
from .ip import Proxy, public_ip, valid_ipv4, valid_ipv6
from .locale import geoip_allowed, get_geolocation, handle_locale
from .pkgman import OS_NAME, get_path, installed_verstr
from .warnings import LeakWarning
from .xpi_dl import add_default_addons

if OS_NAME == 'lin':
    from .virtdisplay import VIRTUAL_DISPLAY

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
    return Screen(max_width=monitor.width, max_height=monitor.height)


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


def check_custom_fingerprint(fingerprint: Fingerprint) -> None:
    """
    Asserts that the passed BrowserForge fingerprint is a valid Firefox fingerprint.
    and warns the user that passing their own fingerprint is not recommended.
    """
    # Check what the browser is
    browser_name = user_agent_parser.ParseUserAgent(fingerprint.navigator.userAgent).get(
        'family', 'Non-Firefox'
    )
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


def _clean_locals(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gets the launch options from the locals of the function.
    """
    del data['playwright']
    del data['persistent_context']
    return data


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
        if prop.endswith('.'):
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
        config, 'navigator.language', 'navigator.languages', 'headers.Accept-Language'
    ):
        LeakWarning.warn('locale', False)
    # Manual User-Agent setting
    if is_domain_set(config, 'headers.User-Agent'):
        LeakWarning.warn('header-ua', False)
    # Manual navigator setting
    if is_domain_set(config, 'navigator.'):
        LeakWarning.warn('navigator', False)
    # Manual screen/window setting
    if is_domain_set(config, 'screen.', 'window.', 'document.body.'):
        LeakWarning.warn('viewport', False)


def get_launch_options(
    *,
    config: Optional[Dict[str, Any]] = None,
    addons: Optional[List[str]] = None,
    fingerprint: Optional[Fingerprint] = None,
    humanize: Optional[Union[bool, float]] = None,
    i_know_what_im_doing: Optional[bool] = None,
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
    headless: Optional[Union[bool, Literal['virtual']]] = None,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    launch_options: Optional[Dict[str, Any]] = None,
    debug: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Builds the launch options for the Camoufox browser.
    """
    # Build the config
    if config is None:
        config = {}

    # Set default values for optional arguments
    if headless is None:
        headless = False
    if addons is None:
        addons = []
    if args is None:
        args = []
    if firefox_user_prefs is None:
        firefox_user_prefs = {}
    if i_know_what_im_doing is None:
        i_know_what_im_doing = False
    if env is None:
        env = cast(Dict[str, Union[str, float, bool]], environ)

    # Handle headless mode cases
    if headless == 'virtual':
        env['DISPLAY'] = VIRTUAL_DISPLAY.new_or_reuse(debug=debug)
        headless = False

    # Warn the user for manual config settings
    if not i_know_what_im_doing:
        warn_manual_config(config)

    # Assert the target OS is valid
    if os:
        check_valid_os(os)

    # Add the default addons
    add_default_addons(addons, exclude_addons)

    # Confirm all addon paths are valid
    if addons:
        confirm_paths(addons)

    # Get the Firefox version
    if ff_version:
        ff_version_str = str(ff_version)
        LeakWarning.warn('ff_version', i_know_what_im_doing)
    else:
        ff_version_str = installed_verstr().split('.', 1)[0]

    # Generate a fingerprint
    if fingerprint is None:
        fingerprint = generate_fingerprint(
            screen=screen or get_screen_cons(headless or 'DISPLAY' in env),
            os=os,
        )
    else:
        # Or use the one passed by the user
        if not i_know_what_im_doing:
            check_custom_fingerprint(fingerprint)

    # Inject the fingerprint into the config
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
        parsed_locale = handle_locale(locale)
        config.update(parsed_locale.as_config())

    # Pass the humanize option
    if humanize:
        set_into(config, 'humanize', True)
        if isinstance(humanize, (int, float)):
            set_into(config, 'humanize:maxTime', humanize)

    # Validate the config
    validate_config(config)

    # Print the config if debug is enabled
    if debug:
        print('[DEBUG] Config:')
        pprint(config)

    # Set Firefox user preferences
    if block_images:
        firefox_user_prefs['permissions.default.image'] = 2
    if block_webrtc:
        firefox_user_prefs['media.peerconnection.enabled'] = False
    if allow_webgl:
        LeakWarning.warn('allow_webgl', i_know_what_im_doing)
        firefox_user_prefs['webgl.disabled'] = False

    # Load the addons
    threaded_try_load_addons(get_debug_port(args), addons)

    # Prepare environment variables to pass to Camoufox
    env_vars = {
        **get_env_vars(config, target_os),
        **env,
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
