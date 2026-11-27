"""Static type definitions and type-system helpers for Rifa'i."""

from __future__ import annotations

from enum import Enum
from typing import Final


class RifaiType(str, Enum):
    """Static types in the Rifa'i language plus internal error sentinel."""

    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    VOID = "void"
    ERROR = "<error>"


_NAMED_TYPES: Final[dict[str, RifaiType]] = {
    "int": RifaiType.INT,
    "float": RifaiType.FLOAT,
    "bool": RifaiType.BOOL,
    "string": RifaiType.STRING,
    "void": RifaiType.VOID,
}


def type_from_name(name: str) -> RifaiType | None:
    """Resolve a Rifa'i type keyword string to its RifaiType enum."""
    return _NAMED_TYPES.get(name)


def is_numeric(rifai_type: RifaiType) -> bool:
    """Return True if the type is int or float."""
    return rifai_type in (RifaiType.INT, RifaiType.FLOAT)


def is_value_type(rifai_type: RifaiType) -> bool:
    """Return True for concrete non-void, non-error value types."""
    return rifai_type in (
        RifaiType.INT,
        RifaiType.FLOAT,
        RifaiType.BOOL,
        RifaiType.STRING,
    )


def is_error_type(rifai_type: RifaiType) -> bool:
    """Return True if the type is the internal error sentinel."""
    return rifai_type is RifaiType.ERROR
