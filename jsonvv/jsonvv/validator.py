from typing import Any, Dict

from .exceptions import MissingRequiredKey, PropertySyntaxError, UnknownProperty
from .parser import parse_type_def
from .strings import string_validator
from .types import Type


class JsonValidator:
    def __init__(self, property_types):
        self.property_types = property_types
        # Create a registry for reference types and parsed type definitions
        self.type_registry = {}
        self.parsed_types = {}
        # Validate and pre-parse all type definitions
        self.parse_types(property_types)

    def validate(self, config_map):
        validate_config(config_map, self.property_types, self.type_registry, self.parsed_types)

    def parse_types(self, property_types: Dict[str, Any], path: str = ""):
        """Validates and pre-parses all type definitions."""
        for key, value in property_types.items():
            current_path = f"{path}.{key}" if path else key

            # Register reference types
            if key.startswith('@'):
                if len(key) == 1:
                    raise PropertySyntaxError(
                        f"Invalid key '{current_path}': '@' must be followed by a reference name"
                    )
                self.type_registry[key[1:]] = value

            # Validate key syntax for required properties
            if key.startswith('*') and len(key) == 1:
                raise PropertySyntaxError(
                    f"Invalid key '{current_path}': '*' must be followed by a property name"
                )

            if isinstance(value, dict):
                # Recursively validate and parse nested dictionaries
                self.parse_types(value, current_path)
            elif isinstance(value, str):
                try:
                    # Pre-parse the type definition and store it
                    self.parsed_types[current_path] = parse_type_def(value, self.type_registry)
                except Exception as e:
                    raise PropertySyntaxError(
                        f"Invalid type definition for '{current_path}': {str(e)}"
                    )
            else:
                raise PropertySyntaxError(
                    f"Invalid type definition for '{current_path}': must be a string or dictionary"
                )


def validate_config(
    config_map: Dict[str, Any],
    property_types: Dict[str, Any],
    type_registry: Dict[str, Type],
    parsed_types: Dict[str, Type],
    parent_registry: Dict[str, Type] = None,
    path: str = "",
) -> None:
    """Validates a configuration map against property types."""

    # Create a new registry for this scope, inheriting from parent if it exists
    local_registry = dict(parent_registry or type_registry)

    # Track required properties
    required_props = {key[1:]: False for key in property_types if key.startswith('*')}

    # Validate each property in config
    for key, value in config_map.items():
        type_def = None
        current_path = f"{path}.{key}" if path else key

        if key in property_types:
            type_def = property_types[key]

            # If the value is a dict and type_def is also a dict, recurse with new scope
            if isinstance(value, dict) and isinstance(type_def, dict):
                validate_config(
                    value, type_def, type_registry, parsed_types, local_registry, current_path
                )
                continue

        elif '*' + key in property_types:
            type_def = property_types['*' + key]
            required_props[key] = True
        else:
            # Check pattern matches
            for pattern, pattern_type in property_types.items():
                if pattern.startswith('@') or pattern.startswith('*'):
                    continue
                if string_validator(key, pattern):
                    type_def = pattern_type
                    current_path = f"{path}.{pattern}" if path else pattern
                    break

        if type_def is None:
            raise UnknownProperty(f"Unknown property: {key}")

        # Use pre-parsed type if available, otherwise parse it
        expected_type = parsed_types.get(current_path)
        if expected_type is None:
            expected_type = parse_type_def(type_def, local_registry)
        expected_type.validate(value, [key], local_registry)

    # Check for missing required properties
    missing_required = [key for key, found in required_props.items() if not found]
    if missing_required:
        raise MissingRequiredKey(f"Missing required properties: {', '.join(missing_required)}")

    # Check for missing required properties
    missing_required = [key for key, found in required_props.items() if not found]
    if missing_required:
        raise MissingRequiredKey(f"Missing required properties: {', '.join(missing_required)}")
