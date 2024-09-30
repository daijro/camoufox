import os.path
import re
from dataclasses import asdict
from typing import Any, Dict, Optional

from browserforge.fingerprints import Fingerprint, FingerprintGenerator
from yaml import CLoader, load

# Load the browserforge.yaml file
with open(os.path.join(os.path.dirname(__file__), 'browserforge.yml'), 'r') as f:
    BROWSERFORGE_DATA = load(f, Loader=CLoader)

FP_GENERATOR = FingerprintGenerator(browser='firefox', os=('linux', 'macos', 'windows'))


def _cast_to_properties(
    camoufox_data: dict, cast_enum: dict, bf_dict: dict, ff_version: Optional[str] = None
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
    return camoufox_data


def generate_fingerprint(**config) -> Fingerprint:
    """
    Generates a Firefox fingerprint with Browserforge.
    """
    return FP_GENERATOR.generate(**config)


if __name__ == "__main__":
    from pprint import pprint

    fp = generate_fingerprint()
    pprint(from_browserforge(fp))
