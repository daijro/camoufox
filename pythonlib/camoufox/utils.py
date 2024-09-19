import os
import sys
from os import environ
from random import randrange
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import numpy as np
import orjson
from browserforge.fingerprints import Fingerprint, Screen
from typing_extensions import TypeAlias
from ua_parser import user_agent_parser

from .addons import (
    DefaultAddons,
    confirm_paths,
    get_debug_port,
    threaded_try_load_addons,
)
from .exceptions import InvalidPropertyType, UnknownProperty
from .fingerprints import from_browserforge, generate
from .pkgman import OS_NAME, get_path
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
    env_vars = {}
    try:
        updated_config_data = orjson.dumps(config_map)
    except orjson.JSONEncodeError as e:
        print(f"Error updating config: {e}")
        sys.exit(1)

    # Split the config into chunks
    chunk_size = 2047 if OS_NAME == 'windows' else 32767
    config_str = updated_config_data.decode('utf-8')

    for i in range(0, len(config_str), chunk_size):
        chunk = config_str[i : i + chunk_size]
        env_name = f"CAMOU_CONFIG_{(i // chunk_size) + 1}"
        try:
            env_vars[env_name] = chunk
        except Exception as e:
            print(f"Error setting {env_name}: {e}")
            sys.exit(1)

    if OS_NAME == 'linux':
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


def get_target_os(config: Dict[str, Any]) -> str:
    """
    Gets the OS from the config if the user agent is set,
    otherwise returns the OS of the current system.
    """
    if config.get("navigator.userAgent"):
        return determine_ua_os(config["navigator.userAgent"])
    return OS_NAME


def determine_ua_os(user_agent: str) -> str:
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


def get_launch_options(
    *,
    config: Optional[Dict[str, Any]] = None,
    addons: Optional[List[str]] = None,
    fingerprint: Optional[Fingerprint] = None,
    exclude_addons: Optional[List[DefaultAddons]] = None,
    screen: Optional[Screen] = None,
    os: Optional[ListOrString] = None,
    user_agent: Optional[ListOrString] = None,
    fonts: Optional[List[str]] = None,
    args: Optional[List[str]] = None,
    executable_path: Optional[str] = None,
    env: Optional[Dict[str, Union[str, float, bool]]] = None,
) -> Dict[str, Any]:
    """
    Builds the launch options for the Camoufox browser.
    """
    # Validate the config
    if config is None:
        config = {}

    if addons is None:
        addons = []
    if args is None:
        args = []

    # Add the default addons
    add_default_addons(addons, exclude_addons)

    # Confirm all addon paths are valid
    if addons:
        confirm_paths(addons)

    # Generate new fingerprint
    if fingerprint is None:
        config = {
            **generate(
                screen=screen,
                os=os,
                user_agent=user_agent,
            ),
            **config,
        }
    else:
        config = {
            **from_browserforge(fingerprint),
            **config,
        }

    # Set a random window.history.length
    config['window.history.length'] = randrange(1, 6)

    if fonts:
        config['fonts'] = fonts

    validate_config(config)

    # Update fonts list
    target_os = get_target_os(config)
    update_fonts(config, target_os)

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
    }
