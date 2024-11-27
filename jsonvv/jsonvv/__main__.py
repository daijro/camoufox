import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from jsonvv.exceptions import InvalidPropertyType, JvvSyntaxError, UnknownProperty
from jsonvv.validator import JsonValidator


def load_json(file_path: Path) -> Dict[str, Any]:
    """
    Load and parse a JSON file.
    """
    try:
        with open(file_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_path}: {e}")
    except FileNotFoundError:
        raise ValueError(f"File not found: {file_path}")


def main():
    """JSON Value Validator - Validate JSON data against a schema."""
    parser = argparse.ArgumentParser(
        description="JSON Value Validator - Validate JSON data against a schema."
    )
    parser.add_argument(
        'properties_file', type=Path, help='JSON file containing the property type definitions'
    )
    parser.add_argument(
        '-i', '--input', type=Path, help='JSON file containing the data to validate'
    )
    parser.add_argument(
        '--check', action='store_true', help='Check if the properties file is valid'
    )

    args = parser.parse_args()

    try:
        # Load property types
        property_types = load_json(args.properties_file)
        validator = JsonValidator(property_types)

        if args.check:
            print("✓ Property types are valid")
            return

        if not args.input:
            parser.error("Either --input or --check must be specified")

        # Load and validate data
        data = load_json(args.input)
        validator.validate(data)
        print("✓ Data is valid")

    except (InvalidPropertyType, UnknownProperty) as e:
        print(f"Validation Error: {e}", file=sys.stderr)
        sys.exit(1)
    except JvvSyntaxError as e:
        print(f"Syntax Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"File Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
