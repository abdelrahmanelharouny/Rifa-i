"""Runtime contract for Rifa'i's intrinsic standard-library functions."""

from __future__ import annotations

BUILTIN_ARITIES: dict[str, int] = {
    "abs": 1,
    "min": 2,
    "max": 2,
    "sqrt": 1,
    "round": 1,
    "to_int": 1,
    "to_float": 1,
    "to_string": 1,
    "contains": 2,
    "starts_with": 2,
    "ends_with": 2,
    "substring": 3,
    "read_text": 1,
    "write_text": 2,
    "file_exists": 1,
}

BUILTIN_FUNCTIONS = frozenset(BUILTIN_ARITIES)
FILE_IO_FUNCTIONS = frozenset({"read_text", "write_text", "file_exists"})
