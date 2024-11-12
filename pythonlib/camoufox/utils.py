import os
import sys
from os import environ
from os.path import abspath
from pathlib import Path
from pprint import pprint
from random import randint, randrange
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
from .locale import geoip_allowed, get_geolocation, handle_locales
from .pkgman import OS_NAME, get_path, installed_verstr, launch_path
from .virtdisplay import VirtualDisplay
from .warnings import LeakWarning
from .xpi_dl import add_default_addons

ListOrString: TypeAlias = Union[Tuple[str, ...], List[str], str]

# Camoufox preferences to cache previous pages and requests
CACHE_PREFS = {
    'browser.sessionhistory.max_entries': 10,
    'browser.sessionhistory.max_total_viewers': -1,
    'browser.cache.memory.enable': True,
    'browser.cache.disk_cache_ssl': True,
    'browser.cache.disk.smart_size.enabled': True,
}


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


def _load_properties(path: Optional[Path] = None) -> Dict[str, str]:
    """
    Loads the properties.json file.
    """
    if path:
        prop_file = str(path.parent / "properties.json")
    else:
        prop_file = get_path("properties.json")
    with open(prop_file, "rb") as f:
        prop_dict = orjson.loads(f.read())

    return {prop['property']: prop['type'] for prop in prop_dict}


def validate_config(config_map: Dict[str, str], path: Optional[Path] = None) -> None:
    """
    Validates the config map.
    """
    property_types = _load_properties(path=path)

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
    elif expected_type == "dict":
        return isinstance(value, dict)
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
        config, 'navigator.language', 'navigator.languages', 'headers.Accept-Language', 'locale:'
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
    # Manual screen/window setting
    if is_domain_set(config, 'screen.', 'window.', 'document.body.'):
        LeakWarning.warn('viewport', False)


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
        await _close(*args, **kwargs)
        if virtual_display:
            virtual_display.kill()

    browser.close = new_close
    browser._virtual_display = virtual_display

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
        _close(*args, **kwargs)
        if virtual_display:
            virtual_display.kill()

    browser.close = new_close
    browser._virtual_display = virtual_display

    return browser


def launch_options(
    *,
    config: Optional[Dict[str, Any]] = None,
    os: Optional[ListOrString] = None,
    block_images: Optional[bool] = None,
    block_webrtc: Optional[bool] = None,
    allow_webgl: Optional[bool] = None,
    geoip: Optional[Union[str, bool]] = None,
    humanize: Optional[Union[bool, float]] = None,
    locale: Optional[Union[str, List[str]]] = None,
    addons: Optional[List[str]] = None,
    fonts: Optional[List[str]] = None,
    exclude_addons: Optional[List[DefaultAddons]] = None,
    screen: Optional[Screen] = None,
    window: Optional[Tuple[int, int]] = None,
    fingerprint: Optional[Fingerprint] = None,
    ff_version: Optional[int] = None,
    headless: Optional[bool] = None,
    executable_path: Optional[Union[str, Path]] = None,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    proxy: Optional[Dict[str, str]] = None,
    enable_cache: Optional[bool] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, Union[str, float, bool]]] = None,
    i_know_what_im_doing: Optional[bool] = None,
    debug: Optional[bool] = None,
    virtual_display: Optional[str] = None,
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
        allow_webgl (Optional[bool]):
            Whether to allow WebGL. To prevent leaks, only use this for special cases.
        geoip (Optional[Union[str, bool]]):
            Calculate longitude, latitude, timezone, country, & locale based on the IP address.
            Pass the target IP address to use, or `True` to find the IP address automatically.
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
        exclude_addons (Optional[List[DefaultAddons]]):
            Default addons to exclude. Passed as a list of camoufox.DefaultAddons enums.
        screen (Optional[Screen]):
            Constrains the screen dimensions of the generated fingerprint.
            Takes a browserforge.fingerprints.Screen instance.
        window (Optional[Tuple[int, int]]):
            Set a fixed window size instead of generating a random one
        fingerprint (Optional[Fingerprint]):
            Use a custom BrowserForge fingerprint. Note: Not all values will be implemented.
            If not provided, a random fingerprint will be generated based on the provided
            `os` & `screen` constraints.
        ff_version (Optional[int]):
            Firefox version to use. Defaults to the current Camoufox version.
            To prevent leaks, only use this for special cases.
        headless (Optional[bool]):
            Whether to run the browser in headless mode. Defaults to False.
            Note: If you are running linux, passing headless='virtual' to Camoufox & AsyncCamoufox
            will use Xvfb.
        executable_path (Optional[Union[str, Path]]):
            Custom Camoufox browser executable path.
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
            Virtual display number. Ex: ':99'. This is handled by Camoufox & AsyncCamoufox.
        **launch_options (Dict[str, Any]):
            Additional Firefox launch options.
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
    if isinstance(executable_path, str):
        # Convert executable path to a Path object
        executable_path = Path(abspath(executable_path))

    # Handle virtual display
    if virtual_display:
        env['DISPLAY'] = virtual_display

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
            window=window,
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
    # Set a fixed font spacing seed
    set_into(config, 'fonts:spacing_seed', randint(0, 2147483647))  # nosec

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
        handle_locales(locale, config)

    # Pass the humanize option
    if humanize:
        set_into(config, 'humanize', True)
        if isinstance(humanize, (int, float)):
            set_into(config, 'humanize:maxTime', humanize)

    # Validate the config
    validate_config(config, path=executable_path)

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

    # Cache previous pages, requests, etc (uses more memory)
    if enable_cache:
        firefox_user_prefs.update(CACHE_PREFS)

    # Load the addons
    threaded_try_load_addons(get_debug_port(args), addons)

    # Prepare environment variables to pass to Camoufox
    env_vars = {
        **get_env_vars(config, target_os),
        **env,
    }
    # Prepare the executable path
    if executable_path:
        executable_path = str(executable_path)
    else:
        executable_path = launch_path()

    return {
        "executable_path": executable_path,
        "args": args,
        "env": env_vars,
        "firefox_user_prefs": firefox_user_prefs,
        "proxy": proxy,
        "headless": headless,
        **(launch_options if launch_options is not None else {}),
    }
