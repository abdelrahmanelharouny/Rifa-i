"""Structured diagnostic models for the Rifa'i compiler and VM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DiagnosticPhase(str, Enum):
    """Compiler or runtime phase that emitted a diagnostic."""

    LEXER = "lexer"
    PARSER = "parser"
    SEMANTIC = "semantic"
    BYTECODE = "bytecode"
    VM = "vm"
    IO = "io"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Represents a structured compiler error or diagnostic with source coordinates."""

    phase: DiagnosticPhase
    message: str
    line: int
    column: int
    start_offset: int | None = None
    end_offset: int | None = None

    def format(self, source_name: str | None = None) -> str:
        """Format the diagnostic into a human-readable message."""
        location = (
            f"{source_name}:{self.line}:{self.column}"
            if source_name
            else f"{self.line}:{self.column}"
        )
        return f"[{self.phase.value}] {location}: {self.message}"

    def __str__(self) -> str:
        return self.format()
