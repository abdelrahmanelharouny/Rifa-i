"""Code-chunk data structures for Rifa'i bytecode."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.instructions import Instruction


@dataclass(frozen=True, slots=True)
class CodeChunk:
    """A straight-line or control-flow instruction sequence.

    Version 1 uses the main chunk only. The arity field is retained in the
    stable chunk model for future function chunks introduced in Phase 4.
    """

    name: str
    instructions: tuple[Instruction, ...]
    local_count: int = 0
    arity: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", tuple(self.instructions))
