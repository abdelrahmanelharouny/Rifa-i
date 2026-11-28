"""Top-level Rifa'i bytecode module model and embedded debugger metadata."""

from __future__ import annotations

from dataclasses import dataclass
import math

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk

LEGACY_FORMAT_VERSION = 1
FUNCTIONS_FORMAT_VERSION = 2
DEBUG_INFO_FORMAT_VERSION = 3
COLLECTIONS_FORMAT_VERSION = 4
NOMINAL_TYPES_FORMAT_VERSION = 5
ALGEBRAIC_TYPES_FORMAT_VERSION = 6
GENERIC_TYPES_FORMAT_VERSION = 7
FORMAT_VERSION = GENERIC_TYPES_FORMAT_VERSION
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
class BytecodeDebugLocal:
    """The source-level identity of one local slot in a code chunk."""

    slot: int
    name: str
    type_name: str


@dataclass(frozen=True, slots=True)
class BytecodeDebugInfo:
    """Optional source and local-symbol information embedded in an RBC v3+ file."""

    source_text: str | None = None
    local_symbols: tuple[tuple[str, tuple[BytecodeDebugLocal, ...]], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "local_symbols",
            tuple((name, tuple(symbols)) for name, symbols in self.local_symbols),
        )

    def as_mapping(self) -> dict[str, dict[int, tuple[str, str]]]:
        """Return the VM's chunk -> slot -> (name, type) lookup shape."""
        return {
            chunk_name: {
                symbol.slot: (symbol.name, symbol.type_name)
                for symbol in symbols
            }
            for chunk_name, symbols in self.local_symbols
        }


@dataclass(frozen=True, slots=True)
class BytecodeModule:
    """Serializable bytecode program with optional source-level debug metadata."""

    constants: tuple[Constant, ...]
    main: CodeChunk
    source_name: str | None = None
    format_version: int = FORMAT_VERSION
    functions: tuple[BytecodeFunction, ...] = ()
    debug_info: BytecodeDebugInfo | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "constants", tuple(self.constants))
        object.__setattr__(self, "functions", tuple(self.functions))
