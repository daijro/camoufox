from dataclasses import dataclass
from typing import Any, Dict, List

from .exceptions import InvalidPropertyType
from .strings import string_validator
from .types import (
    AnyType,
    ArrayType,
    BaseType,
    BoolType,
    DoubleType,
    IntType,
    NilType,
    StringType,
    SubtractionType,
    TupleType,
    Type,
    UnionType,
)


class Parser:
    def __init__(self, type_str: str):
        self.type_str = type_str
        self.pos = 0
        self.length = len(type_str)

    def parse(self) -> Type:
        """Main entry point"""
        result = self.parse_subtraction()  # Start with subtraction instead of union
        self.skip_whitespace()
        if self.pos < self.length:
            raise RuntimeError(f"Unexpected character at position {self.pos}")
        return result

    def parse_union(self) -> Type:
        """Handles type1 | type2 | type3"""
        types = [self.parse_term()]  # Parse first term

        while self.pos < self.length:
            self.skip_whitespace()
            if not self.match('|'):
                break
            types.append(self.parse_term())  # Parse additional terms

        return types[0] if len(types) == 1 else UnionType(types)

    def parse_subtraction(self) -> Type:
        """Handles type1 - type2"""
        left = self.parse_union()  # Start with union

        while self.pos < self.length:
            self.skip_whitespace()
            if not self.match('-'):
                break
            right = self.parse_union()  # Parse right side as union
            left = SubtractionType(left, right)

        return left

    def parse_term(self) -> Type:
        """Handles basic terms and parenthesized expressions"""
        self.skip_whitespace()

        if self.match('('):
            type_obj = self.parse_subtraction()  # Parse subtraction inside parens
            if not self.match(')'):
                raise RuntimeError("Unclosed parenthesis")
            return type_obj

        return self.parse_basic_type()

    def parse_basic_type(self) -> Type:
        """Handles basic types with conditions"""
        name = self.parse_identifier()

        # Special handling for array type
        if name == 'array':
            return self.parse_array_type()

        # Special handling for tuple type
        if name == 'tuple':
            # Don't advance position, let parse_tuple_type handle it
            return self.parse_tuple_type()

        conditions = None
        self.skip_whitespace()

        if self.match('['):
            start = self.pos
            # For all types, just capture everything until the closing bracket
            bracket_count = 1  # Track nested brackets
            while self.pos < self.length:
                if self.type_str[self.pos] == '[':
                    bracket_count += 1
                elif self.type_str[self.pos] == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        break
                self.pos += 1

            if bracket_count > 0:
                raise RuntimeError("Unclosed '['")
            conditions = self.type_str[start : self.pos]

            if not self.match(']'):
                raise RuntimeError("Expected ']'")

        # Return appropriate type based on name
        if name == 'str':
            return StringType(conditions)
        elif name == 'int':
            return IntType(conditions)
        elif name == 'double':
            return DoubleType(conditions)
        elif name == 'bool':
            return BoolType()
        elif name == 'any':
            return AnyType()
        elif name == 'nil':
            return NilType()  # Add this type
        elif name == 'tuple':
            return self.parse_tuple_type()
        elif name.startswith('@'):
            return ReferenceType(name[1:])
        return BaseType(name, conditions)

    def peek(self, char: str) -> bool:
        """Looks ahead for a character without advancing position"""
        self.skip_whitespace()
        return self.pos < self.length and self.type_str[self.pos] == char

    def parse_array_type(self) -> Type:
        """Handles array[type, length?]"""
        if not self.match('['):
            return ArrayType(AnyType(), None)  # Default array type

        # Parse the element type (which could be a complex type)
        element_type = self.parse_subtraction()  # Start with subtraction to handle all cases

        length_conditions = None
        self.skip_whitespace()

        # Check for length conditions after comma
        if self.match(','):
            self.skip_whitespace()
            start = self.pos
            while self.pos < self.length and self.type_str[self.pos] != ']':
                self.pos += 1
            if self.pos >= self.length:
                raise RuntimeError("Unclosed array type")
            length_conditions = self.type_str[start : self.pos].strip()

        if not self.match(']'):
            raise RuntimeError("Expected ']' in array type")

        return ArrayType(element_type, length_conditions)

    def parse_tuple_type(self) -> Type:
        """Handles tuple[type1, type2, ...]"""

        if not self.match('['):
            raise RuntimeError("Expected '[' after 'tuple'")

        types = []
        while True:
            self.skip_whitespace()
            if self.match(']'):
                break

            # Parse complex type expressions within tuple arguments
            type_obj = self.parse_subtraction()  # Start with subtraction to handle all operations
            types.append(type_obj)

            self.skip_whitespace()
            if not self.match(','):
                if self.match(']'):
                    break
                raise RuntimeError("Expected ',' or ']' in tuple type")

        return TupleType(types)

    def parse_identifier(self) -> str:
        """Parses an identifier"""
        self.skip_whitespace()
        start = self.pos

        # Only consume alphanumeric and underscore characters
        while self.pos < self.length and (
            self.type_str[self.pos].isalnum() or self.type_str[self.pos] in '_.@!'
        ):
            self.pos += 1

        if start == self.pos:
            raise RuntimeError(f'Expected identifier at position {self.pos}')

        result = self.type_str[start : self.pos]
        return result

    def skip_whitespace(self) -> None:
        """Skips whitespace characters"""
        while self.pos < self.length and self.type_str[self.pos].isspace():
            self.pos += 1

    def match(self, char: str) -> bool:
        """Tries to match a character, advances position if matched"""
        self.skip_whitespace()
        if self.pos < self.length and self.type_str[self.pos] == char:
            self.pos += 1
            return True
        return False

    def peek_word(self, word: str) -> bool:
        """Looks ahead for a word without advancing position"""
        self.skip_whitespace()
        return (
            self.pos + len(word) <= self.length
            and self.type_str[self.pos : self.pos + len(word)] == word
            and (
                self.pos + len(word) == self.length
                or not self.type_str[self.pos + len(word)].isalnum()
            )
        )


'''
Python's import system is a pain,
so I'm moving DictType and ReferenceType here.
'''


@dataclass
class DictType(Type):
    type_dict: Dict[str, Any]
    type_registry: Dict[str, Any]

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if not isinstance(value, dict):
            raise InvalidPropertyType(f"Expected dict at {'.'.join(path)}, got {type(value)}")

        # Track matched patterns and required keys
        any_pattern_matched = False
        required_patterns = {
            pattern[1:]: False for pattern in self.type_dict if pattern.startswith('*')
        }

        for key, val in value.items():
            pattern_matched = False
            for pattern, type_def in self.type_dict.items():
                # Strip * for required patterns when matching
                match_pattern = pattern[1:] if pattern.startswith('*') else pattern

                if string_validator(key, match_pattern):
                    pattern_matched = True
                    any_pattern_matched = True

                    # Mark required pattern as found
                    if pattern.startswith('*'):
                        required_patterns[match_pattern] = True

                    # Parse the type definition string into a Type object
                    expected_type = parse_type_def(type_def, type_registry)
                    expected_type.validate(val, path + [key], type_registry)

            if not pattern_matched:
                raise InvalidPropertyType(
                    f"Key {key} at {'.'.join(path)} does not match any allowed patterns"
                )

        # Check if all required patterns were matched
        missing_required = [pattern for pattern, found in required_patterns.items() if not found]
        if missing_required:
            raise InvalidPropertyType(
                f"Missing required properties matching patterns: {', '.join(missing_required)} at {'.'.join(path)}"
            )

        if not any_pattern_matched:
            raise InvalidPropertyType(f"No properties at {'.'.join(path)} matched any patterns")


@dataclass
class ReferenceType(Type):
    name: str

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if self.name not in type_registry:
            raise RuntimeError(f"Unknown type reference: @{self.name}")

        ref_type = type_registry[self.name]

        if isinstance(ref_type, dict):
            # Create a DictType for dictionary references
            dict_type = DictType(ref_type, type_registry)
            dict_type.validate(value, path, type_registry)
        else:
            # For non-dictionary types
            ref_type.validate(value, path, type_registry)

    def __str__(self) -> str:
        return f"@{self.name}"


def parse_type_def(type_def: Any, type_registry: Dict[str, Type]) -> Type:
    if isinstance(type_def, str):
        parser = Parser(type_def)
        return parser.parse()
    elif isinstance(type_def, dict):
        return DictType(type_def, type_registry)
    raise InvalidPropertyType(f"Invalid type definition: {type_def}")
