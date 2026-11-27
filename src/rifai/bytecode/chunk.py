"""Immutable code-chunk and function metadata models for Rifa'i bytecode."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.instructions import Instruction


@dataclass(frozen=True, slots=True)
class CodeChunk:
    """An instruction sequence with its local frame layout."""

    name: str
    instructions: tuple[Instruction, ...]
    local_count: int = 0
    arity: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", tuple(self.instructions))


@dataclass(frozen=True, slots=True)
class BytecodeFunction:
    """Function signature and executable chunk stored in a bytecode module."""

    name: str
    chunk: CodeChunk
    parameter_types: tuple[str, ...]
    return_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_types", tuple(self.parameter_types))

    @property
    def arity(self) -> int:
        return len(self.parameter_types)

    @property
    def returns_value(self) -> bool:
        return self.return_type != "void"
