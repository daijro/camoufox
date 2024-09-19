import os.path
from dataclasses import asdict

from browserforge.fingerprints import Fingerprint, FingerprintGenerator
from yaml import CLoader, load

# Load the browserforge.yaml file
with open(os.path.join(os.path.dirname(__file__), 'browserforge.yml'), 'r') as f:
    BROWSERFORGE_DATA = load(f, Loader=CLoader)

FP_GENERATOR = FingerprintGenerator(browser='firefox', os=('linux', 'macos', 'windows'))


def _cast_to_properties(camoufox_data: dict, cast_enum: dict, bf_dict: dict) -> None:
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
            _cast_to_properties(camoufox_data, type_key, data)
            continue
        # Fix values that are out of bounds
        if type_key.startswith("screen.") and isinstance(data, int) and data < 0:
            data = 0
        camoufox_data[type_key] = data


def from_browserforge(fingerprint: Fingerprint) -> dict:
    camoufox_data = {}
    _cast_to_properties(camoufox_data, cast_enum=BROWSERFORGE_DATA, bf_dict=asdict(fingerprint))
    return camoufox_data


def generate(**config) -> dict:
    """
    Generates a Firefox fingerprint.
    """
    data = FP_GENERATOR.generate(**config)
    return from_browserforge(data)


if __name__ == "__main__":
    from pprint import pprint

    pprint(generate())
