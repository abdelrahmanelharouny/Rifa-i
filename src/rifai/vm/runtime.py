"""Runtime values, result models, and VM exception types for Rifa'i."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase


@dataclass(slots=True)
class ArrayValue:
    """Mutable homogeneous array allocated by the Rifa'i VM."""

    element_type: str
    items: list[RuntimeValue]


@dataclass(slots=True)
class StructValue:
    """Mutable nominal record with a runtime-checked field schema."""

    type_name: str
    field_types: dict[str, str]
    fields: dict[str, RuntimeValue]


@dataclass(frozen=True, slots=True)
class EnumValue:
    """Immutable enum variant with an ordered, typed payload."""

    type_name: str
    variant: str
    payloads: tuple[RuntimeValue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "payloads", tuple(self.payloads))


RuntimeValue = int | float | bool | str | ArrayValue | StructValue | EnumValue


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Captured output and final observable state from one VM execution."""

    output: tuple[str, ...]
    globals: Mapping[str, RuntimeValue]
    instructions_executed: int
    final_stack: tuple[RuntimeValue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", tuple(self.output))
        object.__setattr__(self, "globals", MappingProxyType(dict(self.globals)))
        object.__setattr__(self, "final_stack", tuple(self.final_stack))


class VMRuntimeError(RuntimeError):
    """Runtime failure enriched with a source-aware VM diagnostic."""

    def __init__(self, message: str, line: int = 1, column: int = 1) -> None:
        super().__init__(message)
        self.diagnostic = Diagnostic(
            phase=DiagnosticPhase.VM,
            message=message,
            line=line,
            column=column,
        )


class BytecodeValidationError(RuntimeError):
    """Raised when the VM is asked to execute invalid bytecode."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        super().__init__("Bytecode validation failed.")
        self.diagnostics = diagnostics


def format_value(value: RuntimeValue) -> str:
    """Format primitive values and nested VM arrays for user-facing output."""
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, ArrayValue):
        return "[" + ", ".join(format_value(item) for item in value.items) + "]"
    if isinstance(value, StructValue):
        fields = ", ".join(
            f"{name}: {format_value(item)}"
            for name, item in value.fields.items()
        )
        return f"{value.type_name}{{{fields}}}"
    if isinstance(value, EnumValue):
        if value.payloads:
            payload = ", ".join(format_value(item) for item in value.payloads)
            return f"{value.type_name}.{value.variant}({payload})"
        return f"{value.type_name}.{value.variant}"
    return str(value)
