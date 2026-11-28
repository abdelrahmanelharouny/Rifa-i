"""Static primitive, collection, and nominal type definitions for Rifa'i."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, TypeAlias


class RifaiType(str, Enum):
    """Static primitive and one-dimensional typed-array types."""

    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    INT_ARRAY = "int[]"
    FLOAT_ARRAY = "float[]"
    BOOL_ARRAY = "bool[]"
    STRING_ARRAY = "string[]"
    VOID = "void"
    ERROR = "<error>"


@dataclass(frozen=True, slots=True)
class UserDefinedType:
    """A nominal struct or enum type, distinguished by name and kind."""

    name: str
    kind: str

    @property
    def value(self) -> str:
        return self.name


StaticType: TypeAlias = RifaiType | UserDefinedType


_NAMED_TYPES: Final[dict[str, RifaiType]] = {
    "int": RifaiType.INT,
    "float": RifaiType.FLOAT,
    "bool": RifaiType.BOOL,
    "string": RifaiType.STRING,
    "int[]": RifaiType.INT_ARRAY,
    "float[]": RifaiType.FLOAT_ARRAY,
    "bool[]": RifaiType.BOOL_ARRAY,
    "string[]": RifaiType.STRING_ARRAY,
    "void": RifaiType.VOID,
}

_ARRAY_ELEMENT_TYPES: Final[dict[RifaiType, RifaiType]] = {
    RifaiType.INT_ARRAY: RifaiType.INT,
    RifaiType.FLOAT_ARRAY: RifaiType.FLOAT,
    RifaiType.BOOL_ARRAY: RifaiType.BOOL,
    RifaiType.STRING_ARRAY: RifaiType.STRING,
}
_ELEMENT_ARRAY_TYPES: Final[dict[RifaiType, RifaiType]] = {
    element: array for array, element in _ARRAY_ELEMENT_TYPES.items()
}


def type_from_name(name: str) -> RifaiType | None:
    """Resolve a primitive or typed-array textual annotation."""
    return _NAMED_TYPES.get(name)


def type_name(value: StaticType) -> str:
    """Return the stable bytecode/debug name for a static type."""
    return value.value if isinstance(value, RifaiType) else value.name


def array_element_type(rifai_type: StaticType) -> RifaiType | None:
    """Return the primitive element type of a one-dimensional array type."""
    return _ARRAY_ELEMENT_TYPES.get(rifai_type) if isinstance(rifai_type, RifaiType) else None


def array_type_for(element_type: StaticType) -> RifaiType | None:
    """Return the corresponding array type for a primitive element type."""
    return _ELEMENT_ARRAY_TYPES.get(element_type) if isinstance(element_type, RifaiType) else None


def is_array_type(rifai_type: StaticType) -> bool:
    return isinstance(rifai_type, RifaiType) and rifai_type in _ARRAY_ELEMENT_TYPES


def is_numeric(rifai_type: StaticType) -> bool:
    return rifai_type in (RifaiType.INT, RifaiType.FLOAT)


def is_value_type(rifai_type: StaticType) -> bool:
    """Return True for primitive values valid in scalar equality operations."""
    return rifai_type in (
        RifaiType.INT,
        RifaiType.FLOAT,
        RifaiType.BOOL,
        RifaiType.STRING,
    ) or isinstance(rifai_type, UserDefinedType)


def is_error_type(rifai_type: StaticType) -> bool:
    return rifai_type is RifaiType.ERROR
