from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .exceptions import InvalidPropertyType
from .strings import string_validator

TYPE_NAMES = {'array', 'tuple', 'str', 'int', 'double', 'bool', 'any', 'nil', 'tuple'}


class Type(ABC):
    @abstractmethod
    def validate(self, value: Any, path: List[str], type_registry: Dict[str, 'Type']) -> None:
        pass


@dataclass
class BaseType(Type):
    """Base class for all types"""

    name: str
    conditions: Optional[str] = None

    def __post_init__(self):
        # Raise error early
        if not self.name.startswith('@') and self.name not in TYPE_NAMES:
            raise InvalidPropertyType(f'Unknown base type {self.name}')

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if self.name in type_registry:
            type_registry[self.name].validate(value, path, type_registry)
        else:
            raise RuntimeError(f'Unknown base type {self.name}')


@dataclass
class NilType(Type):
    """Represents a nil/null type"""

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if value is not None:
            raise InvalidPropertyType(
                f"Invalid value at {'.'.join(path)}: expected nil, got {value}"
            )

    def __str__(self) -> str:
        return "nil"


@dataclass
class StringType(Type):
    pattern: Optional[str] = None

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if not isinstance(value, str):
            raise InvalidPropertyType(
                f"Invalid value at {'.'.join(path)}: expected string, got {type(value).__name__}"
            )

        if self.pattern:
            if not string_validator(value, self.pattern):
                raise InvalidPropertyType(
                    f"Invalid value at {'.'.join(path)}: {value} does not match pattern '{self.pattern}'"
                )

    def __str__(self) -> str:
        return f"str[{self.pattern}]" if self.pattern else "str"


@dataclass
class NumericalType(Type):
    conditions: Optional[str] = None
    numeric_type: Type = float  # Default to float
    type_name: str = "number"  # For error messages

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        allowed_types = (int, float) if self.numeric_type is float else (int,)
        if not isinstance(value, allowed_types):
            raise InvalidPropertyType(
                f"Invalid value at {'.'.join(path)}: expected {self.type_name}, got {type(value).__name__}"
            )
        if self.conditions and not self._check_conditions(self.numeric_type(value)):
            raise InvalidPropertyType(
                f"Invalid value at {'.'.join(path)}: {value} does not match conditions '{self.conditions}'"
            )

    def _check_conditions(self, value: Union[int, float]) -> bool:
        if not self.conditions:
            return True

        # Split by comma and handle each condition
        conditions = [c.strip() for c in self.conditions.split(',')]

        for condition in conditions:
            try:
                # Handle comparisons
                if '>=' in condition:
                    if value >= self.numeric_type(condition.replace('>=', '')):
                        return True
                elif '<=' in condition:
                    if value <= self.numeric_type(condition.replace('<=', '')):
                        return True
                elif '>' in condition:
                    if value > self.numeric_type(condition.replace('>', '')):
                        return True
                elif '<' in condition:
                    if value < self.numeric_type(condition.replace('<', '')):
                        return True
                # Handle ranges (e.g., "1.5-5.5")
                elif '-' in condition[1:]:
                    # split by the -, ignoring the first character
                    range_s, range_e = condition[1:].split('-', 1)
                    range_s = self.numeric_type(condition[0] + range_s)
                    range_e = self.numeric_type(range_e)
                    if range_s <= value <= range_e:
                        return True
                # Handle single values
                else:
                    if value == self.numeric_type(condition):
                        return True
            except ValueError:
                continue

        return False

    def __str__(self) -> str:
        return f"{self.type_name}[{self.conditions}]" if self.conditions else self.type_name


@dataclass
class IntType(NumericalType):
    def __init__(self, conditions: Optional[str] = None):
        super().__init__(conditions=conditions, numeric_type=int, type_name="int")


@dataclass
class DoubleType(NumericalType):
    def __init__(self, conditions: Optional[str] = None):
        super().__init__(conditions=conditions, numeric_type=float, type_name="double")


@dataclass
class AnyType(Type):
    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        # Any type accepts all values
        pass

    def __str__(self) -> str:
        return "any"


@dataclass
class BoolType(Type):
    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if not isinstance(value, bool):
            raise InvalidPropertyType(
                f"Invalid value at {'.'.join(path)}: expected bool, got {type(value).__name__}"
            )


@dataclass
class ArrayType(Type):
    element_type: Type
    length_conditions: Optional[str] = None

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if not isinstance(value, list):
            raise InvalidPropertyType(
                f"Invalid value at {'.'.join(path)}: expected array, got {type(value).__name__}"
            )

        if self.length_conditions:
            array_len = len(value)
            length_validator = IntType(self.length_conditions)
            try:
                length_validator._check_conditions(array_len)
            except Exception:
                raise InvalidPropertyType(
                    f"Invalid array length at {'.'.join(path)}: got length {array_len}"
                )

        for i, item in enumerate(value):
            self.element_type.validate(item, path + [str(i)], type_registry)


@dataclass
class TupleType(Type):
    element_types: List[Type]

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        if not isinstance(value, (list, tuple)):
            raise InvalidPropertyType(
                f"Invalid value at {'.'.join(path)}: expected tuple, got {type(value).__name__}"
            )

        if len(value) != len(self.element_types):
            raise InvalidPropertyType(
                f"Invalid tuple length at {'.'.join(path)}: expected {len(self.element_types)}, got {len(value)}"
            )

        for i, (item, expected_type) in enumerate(zip(value, self.element_types)):
            expected_type.validate(item, path + [str(i)], type_registry)


@dataclass
class UnionType(Type):
    types: List[Type]

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        errors = []
        for t in self.types:
            try:
                t.validate(value, path, type_registry)
                return  # If any type validates successfully, we're done
            except InvalidPropertyType as e:
                errors.append(str(e))

        # If we get here, none of the types validated
        raise InvalidPropertyType(
            f"Invalid value at {'.'.join(path)}: {value} does not match any of the allowed types"
        )

    def __str__(self) -> str:
        return f"({' | '.join(str(t) for t in self.types)})"


@dataclass
class SubtractionType(Type):
    base_type: Type
    subtracted_type: Type

    def validate(self, value: Any, path: List[str], type_registry: Dict[str, Type]) -> None:
        path_str = '.'.join(path)

        # First check if value matches base type
        matches_base = True
        try:
            self.base_type.validate(value, path, type_registry)
        except InvalidPropertyType:
            matches_base = False
            raise

        # Then check if value matches subtracted type
        matches_subtracted = True
        try:
            self.subtracted_type.validate(value, path, type_registry)
            matches_subtracted = True
        except InvalidPropertyType:
            matches_subtracted = False

        # Final validation decision
        if matches_base and matches_subtracted:
            raise InvalidPropertyType(f"Invalid value at {path_str}: {value} matches excluded type")
        elif matches_base and not matches_subtracted:
            return
        else:
            raise InvalidPropertyType(
                f"Invalid value at {path_str}: {value} does not match base type"
            )

    def __str__(self) -> str:
        return f"({self.base_type} - {self.subtracted_type})"
