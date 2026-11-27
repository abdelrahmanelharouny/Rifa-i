"""Static type definitions and type-system helpers for Rifa'i."""

from __future__ import annotations

from enum import Enum
from typing import Final


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
    """Resolve a textual type annotation to a static Rifa'i type."""
    return _NAMED_TYPES.get(name)


def array_element_type(rifai_type: RifaiType) -> RifaiType | None:
    """Return the primitive element type of a one-dimensional array type."""
    return _ARRAY_ELEMENT_TYPES.get(rifai_type)


def array_type_for(element_type: RifaiType) -> RifaiType | None:
    """Return the corresponding array type for a primitive element type."""
    return _ELEMENT_ARRAY_TYPES.get(element_type)


def is_array_type(rifai_type: RifaiType) -> bool:
    return rifai_type in _ARRAY_ELEMENT_TYPES


def is_numeric(rifai_type: RifaiType) -> bool:
    return rifai_type in (RifaiType.INT, RifaiType.FLOAT)


def is_value_type(rifai_type: RifaiType) -> bool:
    """Return True for primitive types valid in scalar equality operations."""
    return rifai_type in (
        RifaiType.INT,
        RifaiType.FLOAT,
        RifaiType.BOOL,
        RifaiType.STRING,
    )


def is_error_type(rifai_type: RifaiType) -> bool:
    return rifai_type is RifaiType.ERROR
