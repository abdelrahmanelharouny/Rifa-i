"""Top-level Rifa'i bytecode module model."""

from __future__ import annotations

from dataclasses import dataclass
import math

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk

FORMAT_VERSION = 2
LEGACY_FORMAT_VERSION = 1
MAGIC = b"RIFAI-RBC\n"

Constant = int | float | bool | str


def is_constant(value: object) -> bool:
    """Return whether a value is a supported Rifa'i bytecode constant."""
    if type(value) is bool:
        return True
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return isinstance(value, str)


@dataclass(frozen=True, slots=True)
class BytecodeModule:
    """Serializable bytecode program containing a main chunk and functions."""

    constants: tuple[Constant, ...]
    main: CodeChunk
    source_name: str | None = None
    format_version: int = FORMAT_VERSION
    functions: tuple[BytecodeFunction, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "constants", tuple(self.constants))
        object.__setattr__(self, "functions", tuple(self.functions))
