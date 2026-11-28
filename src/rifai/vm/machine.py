"""A verified stack-based bytecode interpreter with function call frames."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import tempfile
from dataclasses import dataclass
import math

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode
from rifai.bytecode.module import BytecodeModule
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.stdlib import BUILTIN_ARITIES, FILE_IO_FUNCTIONS
from rifai.vm.runtime import (
    ArrayValue,
    StructValue,
    EnumValue,
    BytecodeValidationError,
    ExecutionResult,
    RuntimeValue,
    VMRuntimeError,
    format_value,
)

_UNINITIALIZED = object()
_ARRAY_OPCODE_TYPES = {
    Opcode.ARRAY_NEW_INT: "int",
    Opcode.ARRAY_NEW_FLOAT: "float",
    Opcode.ARRAY_NEW_BOOL: "bool",
    Opcode.ARRAY_NEW_STRING: "string",
}


@dataclass(slots=True)
class _CallFrame:
    """Mutable execution state for one active main/function chunk."""

    chunk: CodeChunk
    name: str
    locals: list[RuntimeValue | object]
    ip: int
    stack_base: int
    returns_value: bool
    is_main: bool = False


@dataclass(frozen=True, slots=True)
class DebugLocalSnapshot:
    """Source-level local variable state captured before one instruction."""

    slot: int
    name: str
    type_name: str
    initialized: bool
    value: RuntimeValue | None


@dataclass(frozen=True, slots=True)
class DebugFrameSnapshot:
    """Read-only view of one active VM call frame."""

    name: str
    instruction_pointer: int
    stack_base: int
    is_main: bool
    locals: tuple[DebugLocalSnapshot, ...]


@dataclass(frozen=True, slots=True)
class InstructionSnapshot:
    """Immutable VM state immediately before executing an instruction."""

    instruction: Instruction
    frame_name: str
    instruction_index: int
    frames: tuple[DebugFrameSnapshot, ...]
    operand_stack: tuple[RuntimeValue, ...]
    globals: tuple[tuple[str, RuntimeValue], ...]
    instructions_executed: int


class VirtualMachine:
    """Execute verified Rifa'i bytecode with isolated locals and recursive calls."""

    def __init__(
        self,
        *,
        max_steps: int = 1_000_000,
        max_stack_depth: int = 100_000,
        max_call_depth: int = 1_024,
        max_string_length: int = 16 * 1024 * 1024,
        max_output_chars: int = 16 * 1024 * 1024,
        max_integer_bits: int = 1_000_000,
        max_array_items: int = 1_000_000,
        allow_file_io: bool = False,
        file_root: str | Path | None = None,
        max_file_bytes: int = 1_048_576,
    ) -> None:
        limits = {
            "max_steps": max_steps,
            "max_stack_depth": max_stack_depth,
            "max_call_depth": max_call_depth,
            "max_string_length": max_string_length,
            "max_output_chars": max_output_chars,
            "max_integer_bits": max_integer_bits,
            "max_array_items": max_array_items,
            "max_file_bytes": max_file_bytes,
        }
        for name, value in limits.items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        self.max_steps = max_steps
        self.max_stack_depth = max_stack_depth
        self.max_call_depth = max_call_depth
        self.max_string_length = max_string_length
        self.max_output_chars = max_output_chars
        self.max_integer_bits = max_integer_bits
        self.max_array_items = max_array_items
        if type(allow_file_io) is not bool:
            raise ValueError("allow_file_io must be a boolean.")
        self.allow_file_io = allow_file_io
        self.file_root = Path(file_root).resolve() if file_root is not None else None
        if allow_file_io and self.file_root is None:
            raise ValueError("file_root is required when file I/O is enabled.")
        self.max_file_bytes = max_file_bytes

    @staticmethod
    def _matches_type(value: RuntimeValue, type_name: str) -> bool:
        if type_name.endswith("[]"):
            element_type = type_name[:-2]
            return (
                isinstance(value, ArrayValue)
                and value.element_type == element_type
                and all(
                    VirtualMachine._matches_type(item, element_type)
                    for item in value.items
                )
            )
        if type_name == "bool":
            return type(value) is bool
        if type_name == "int":
            return type(value) is int
        if type_name == "float":
            return type(value) is float
        if type_name == "string":
            return type(value) is str
        if isinstance(value, StructValue):
            return value.type_name == type_name
        if isinstance(value, EnumValue):
            return value.type_name == type_name
        return False

    def execute(
        self,
        module: BytecodeModule,
        *,
        initial_globals: Mapping[str, RuntimeValue] | None = None,
        on_instruction: Callable[[InstructionSnapshot], None] | None = None,
        debug_symbols: Mapping[str, Mapping[int, tuple[str, str]]] | None = None,
    ) -> ExecutionResult:
        """Verify and execute a module, optionally observing each pre-instruction state."""
        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            raise BytecodeValidationError(validation.diagnostics)

        if initial_globals is not None and not isinstance(initial_globals, Mapping):
            raise TypeError("initial_globals must be a mapping or None.")

        globals_: dict[str, RuntimeValue] = {}
        for name, value in (initial_globals or {}).items():
            if not isinstance(name, str) or not name:
                raise ValueError("Initial global names must be non-empty strings.")
            if type(value) not in (int, float, bool, str) and not isinstance(value, (ArrayValue, StructValue, EnumValue)):
                raise ValueError(f"Initial global {name!r} has an unsupported value.")
            if isinstance(value, (StructValue, EnumValue)) and not self._matches_type(value, value.type_name):
                raise ValueError(f"Initial global {name!r} has an invalid nominal value.")
            if isinstance(value, StructValue):
                if (
                    not isinstance(value.field_types, dict)
                    or not isinstance(value.fields, dict)
                    or any(
                        field not in value.field_types
                        or not isinstance(value.field_types[field], str)
                        or not self._matches_type(field_value, value.field_types[field])
                        for field, field_value in value.fields.items()
                    )
                ):
                    raise ValueError(f"Initial global {name!r} has an invalid struct schema or field value.")
            if isinstance(value, EnumValue) and (
                not isinstance(value.variant, str) or not value.variant
            ):
                raise ValueError(f"Initial global {name!r} has an invalid enum variant.")
            if isinstance(value, ArrayValue):
                if value.element_type not in {"int", "float", "bool", "string"}:
                    raise ValueError(f"Initial global {name!r} has an invalid array element type.")
                if len(value.items) > self.max_array_items or not all(
                    self._matches_type(item, value.element_type)
                    and not (
                        type(item) is int
                        and item.bit_length() > self.max_integer_bits
                    )
                    and not (type(item) is float and not math.isfinite(item))
                    and not (
                        type(item) is str
                        and len(item) > self.max_string_length
                    )
                    for item in value.items
                ):
                    raise ValueError(f"Initial global {name!r} is not a valid bounded homogeneous array.")
            if type(value) is float and not math.isfinite(value):
                raise ValueError(f"Initial global {name!r} must be a finite float.")
            if type(value) is int and value.bit_length() > self.max_integer_bits:
                raise ValueError(
                    f"Initial global {name!r} exceeds the integer bit limit "
                    f"({self.max_integer_bits})."
                )
            if type(value) is str and len(value) > self.max_string_length:
                raise ValueError(
                    f"Initial global {name!r} exceeds the string length limit "
                    f"({self.max_string_length})."
                )
            globals_[name] = value

        functions: dict[str, BytecodeFunction] = {
            function.name: function for function in module.functions
        }
        stack: list[RuntimeValue] = []
        output: list[str] = []
        output_chars = 0
        frames: list[_CallFrame] = [
            _CallFrame(
                chunk=module.main,
                name="<main>",
                locals=[_UNINITIALIZED for _ in range(module.main.local_count)],
                ip=0,
                stack_base=0,
                returns_value=False,
                is_main=True,
            )
        ]
        executed = 0

        def fault(message: str, instruction: Instruction) -> VMRuntimeError:
            location = instruction.location
            return VMRuntimeError(
                message,
                location.line if location else 1,
                location.column if location else 1,
            )

        def resolve_file_path(raw_path: object, instruction: Instruction) -> Path:
            if not self.allow_file_io or self.file_root is None:
                raise fault("File I/O is disabled for this VM instance.", instruction)
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise fault("File path must be a non-empty relative string.", instruction)
            relative = Path(raw_path)
            if relative.is_absolute() or any(part in ("..", "") for part in relative.parts):
                raise fault("File path must stay inside the configured project directory.", instruction)
            candidate = (self.file_root / relative).resolve()
            try:
                candidate.relative_to(self.file_root)
            except ValueError:
                raise fault("File path escapes the configured project directory.", instruction) from None
            return candidate

        def pop(instruction: Instruction) -> RuntimeValue:
            if not stack:
                raise fault("Operand stack underflow.", instruction)
            return stack.pop()

        def push(value: RuntimeValue, instruction: Instruction) -> None:
            if type(value) is float and not math.isfinite(value):
                raise fault("Floating-point result is not finite.", instruction)
            if type(value) is int and value.bit_length() > self.max_integer_bits:
                raise fault(
                    f"Integer bit limit ({self.max_integer_bits}) exceeded.",
                    instruction,
                )
            if type(value) is str and len(value) > self.max_string_length:
                raise fault(
                    f"String length limit ({self.max_string_length}) exceeded.",
                    instruction,
                )
            if len(stack) >= self.max_stack_depth:
                raise fault(
                    f"Operand stack limit ({self.max_stack_depth}) exceeded.",
                    instruction,
                )
            stack.append(value)

        while frames:
            frame = frames[-1]
            if frame.ip < 0 or frame.ip >= len(frame.chunk.instructions):
                raise VMRuntimeError(
                    f"Instruction pointer escaped code chunk '{frame.name}'."
                )
            if executed >= self.max_steps:
                raise fault(
                    f"Instruction limit ({self.max_steps}) exceeded.",
                    frame.chunk.instructions[frame.ip],
                )

            instruction = frame.chunk.instructions[frame.ip]
            if on_instruction is not None:
                frame_snapshots: list[DebugFrameSnapshot] = []
                for active_frame in frames:
                    names = (debug_symbols or {}).get(active_frame.name, {})
                    local_snapshots = []
                    for slot, local_value in enumerate(active_frame.locals):
                        local_name, type_name = names.get(
                            slot, (f"local[{slot}]", "unknown")
                        )
                        initialized = local_value is not _UNINITIALIZED
                        local_snapshots.append(
                            DebugLocalSnapshot(
                                slot=slot,
                                name=local_name,
                                type_name=type_name,
                                initialized=initialized,
                                value=local_value if initialized else None,
                            )
                        )
                    frame_snapshots.append(
                        DebugFrameSnapshot(
                            name=active_frame.name,
                            instruction_pointer=active_frame.ip,
                            stack_base=active_frame.stack_base,
                            is_main=active_frame.is_main,
                            locals=tuple(local_snapshots),
                        )
                    )
                on_instruction(
                    InstructionSnapshot(
                        instruction=instruction,
                        frame_name=frame.name,
                        instruction_index=frame.ip,
                        frames=tuple(frame_snapshots),
                        operand_stack=tuple(stack),
                        globals=tuple(sorted(globals_.items())),
                        instructions_executed=executed,
                    )
                )
            opcode = instruction.opcode
            next_ip = frame.ip + 1
            executed += 1

            if opcode is Opcode.CONSTANT:
                push(module.constants[instruction.operand], instruction)
            elif opcode is Opcode.POP:
                pop(instruction)
            elif opcode is Opcode.DUP:
                if not stack:
                    raise fault("DUP requires a value on the operand stack.", instruction)
                push(stack[-1], instruction)
            elif opcode is Opcode.LOAD_LOCAL:
                value = frame.locals[instruction.operand]
                if value is _UNINITIALIZED:
                    raise fault(
                        f"Local slot {instruction.operand} was read before initialization.",
                        instruction,
                    )
                push(value, instruction)
            elif opcode is Opcode.STORE_LOCAL:
                frame.locals[instruction.operand] = pop(instruction)
            elif opcode is Opcode.LOAD_GLOBAL:
                if instruction.operand not in globals_:
                    raise fault(
                        f"Undefined global variable '{instruction.operand}'.",
                        instruction,
                    )
                push(globals_[instruction.operand], instruction)
            elif opcode is Opcode.STORE_GLOBAL:
                globals_[instruction.operand] = pop(instruction)
            elif opcode in _ARRAY_OPCODE_TYPES:
                count = instruction.operand
                if len(stack) < count:
                    raise fault("Array construction has insufficient element values.", instruction)
                values = stack[-count:] if count else []
                if count:
                    del stack[-count:]
                element_type = _ARRAY_OPCODE_TYPES[opcode]
                if not all(self._matches_type(value, element_type) for value in values):
                    raise fault(
                        f"{opcode.value} received an element with the wrong runtime type.",
                        instruction,
                    )
                if count > self.max_array_items:
                    raise fault(
                        f"Array item limit ({self.max_array_items}) exceeded.",
                        instruction,
                    )
                push(ArrayValue(element_type, list(values)), instruction)
            elif opcode is Opcode.STRUCT_NEW:
                type_name, schema_text = instruction.operand.split("|", 1)
                field_types: dict[str, str] = {}
                for entry in schema_text.split(","):
                    field_name, field_type = entry.split(":", 1)
                    field_types[field_name] = field_type
                push(StructValue(type_name, field_types, {}), instruction)
            elif opcode is Opcode.FIELD_GET:
                record = pop(instruction)
                if not isinstance(record, StructValue):
                    raise fault("FIELD_GET requires a struct value.", instruction)
                if instruction.operand not in record.field_types:
                    raise fault(f"Struct '{record.type_name}' has no field '{instruction.operand}'.", instruction)
                if instruction.operand not in record.fields:
                    raise fault(f"Field '{instruction.operand}' was read before initialization.", instruction)
                push(record.fields[instruction.operand], instruction)
            elif opcode is Opcode.FIELD_SET:
                value = pop(instruction)
                record = pop(instruction)
                if not isinstance(record, StructValue):
                    raise fault("FIELD_SET requires a struct value.", instruction)
                expected = record.field_types.get(instruction.operand)
                if expected is None:
                    raise fault(f"Struct '{record.type_name}' has no field '{instruction.operand}'.", instruction)
                if not self._matches_type(value, expected):
                    raise fault(f"Field '{instruction.operand}' expects '{expected}'.", instruction)
                record.fields[instruction.operand] = value
            elif opcode is Opcode.ENUM_NEW:
                enum_name, variants_text, variant = instruction.operand.split("|", 2)
                variants = variants_text.split(",")
                if variant not in variants:
                    raise fault(f"Enum '{enum_name}' has no variant '{variant}'.", instruction)
                push(EnumValue(enum_name, variant), instruction)
            elif opcode is Opcode.ENUM_NEW_PAYLOAD:
                enum_name, variant, payload_types_text = instruction.operand.split("|", 2)
                payload_types = payload_types_text.split(",") if payload_types_text else []
                if len(stack) < len(payload_types):
                    raise fault("Enum construction has insufficient payload values.", instruction)
                values = stack[-len(payload_types):] if payload_types else []
                if payload_types:
                    del stack[-len(payload_types):]
                for index, (value, expected) in enumerate(zip(values, payload_types)):
                    if not self._matches_type(value, expected):
                        raise fault(f"Payload {index + 1} of '{enum_name}.{variant}' expects '{expected}'.", instruction)
                push(EnumValue(enum_name, variant, tuple(values)), instruction)
            elif opcode is Opcode.ENUM_IS:
                enum_value = pop(instruction)
                enum_name, variant = instruction.operand.split("|", 1)
                if not isinstance(enum_value, EnumValue) or enum_value.type_name != enum_name:
                    raise fault(f"ENUM_IS requires a value of enum type '{enum_name}'.", instruction)
                push(enum_value.variant == variant, instruction)
            elif opcode is Opcode.ENUM_GET:
                enum_value = pop(instruction)
                enum_name, variant, index_text, expected = instruction.operand.split("|", 3)
                index = int(index_text)
                if not isinstance(enum_value, EnumValue) or enum_value.type_name != enum_name or enum_value.variant != variant:
                    raise fault(f"ENUM_GET requires '{enum_name}.{variant}'.", instruction)
                if index < 0 or index >= len(enum_value.payloads):
                    raise fault(f"Enum payload index {index} is out of range.", instruction)
                value = enum_value.payloads[index]
                if not self._matches_type(value, expected):
                    raise fault(f"Enum payload {index + 1} has an invalid runtime type.", instruction)
                push(value, instruction)
            elif opcode is Opcode.ARRAY_GET:
                index = pop(instruction)
                array = pop(instruction)
                if not isinstance(array, ArrayValue) or type(index) is not int:
                    raise fault("ARRAY_GET requires an array and an integer index.", instruction)
                if index < 0 or index >= len(array.items):
                    raise fault(
                        f"Array index {index} is out of bounds for length {len(array.items)}.",
                        instruction,
                    )
                push(array.items[index], instruction)
            elif opcode is Opcode.ARRAY_SET:
                value = pop(instruction)
                index = pop(instruction)
                array = pop(instruction)
                if not isinstance(array, ArrayValue) or type(index) is not int:
                    raise fault("ARRAY_SET requires an array and an integer index.", instruction)
                if not self._matches_type(value, array.element_type):
                    raise fault("ARRAY_SET value does not match the array element type.", instruction)
                if index < 0 or index >= len(array.items):
                    raise fault(
                        f"Array index {index} is out of bounds for length {len(array.items)}.",
                        instruction,
                    )
                array.items[index] = value
            elif opcode is Opcode.LENGTH:
                value = pop(instruction)
                if isinstance(value, ArrayValue):
                    push(len(value.items), instruction)
                elif type(value) is str:
                    push(len(value), instruction)
                else:
                    raise fault("LENGTH requires a string or array.", instruction)
            elif opcode is Opcode.ARRAY_PUSH:
                value = pop(instruction)
                array = pop(instruction)
                if not isinstance(array, ArrayValue):
                    raise fault("ARRAY_PUSH requires an array as its first argument.", instruction)
                if not self._matches_type(value, array.element_type):
                    raise fault("ARRAY_PUSH value does not match the array element type.", instruction)
                if len(array.items) >= self.max_array_items:
                    raise fault(
                        f"Array item limit ({self.max_array_items}) exceeded.",
                        instruction,
                    )
                array.items.append(value)
            elif opcode is Opcode.ARRAY_POP:
                array = pop(instruction)
                if not isinstance(array, ArrayValue):
                    raise fault("ARRAY_POP requires an array.", instruction)
                if not array.items:
                    raise fault("Cannot pop from an empty array.", instruction)
                push(array.items.pop(), instruction)
            elif opcode is Opcode.NEGATE:
                value = pop(instruction)
                if type(value) not in (int, float):
                    raise fault("Unary NEGATE requires an int or float.", instruction)
                push(-value, instruction)
            elif opcode is Opcode.NOT:
                value = pop(instruction)
                if type(value) is not bool:
                    raise fault("NOT requires a bool.", instruction)
                push(not value, instruction)
            elif opcode in (
                Opcode.ADD,
                Opcode.SUBTRACT,
                Opcode.MULTIPLY,
                Opcode.DIVIDE,
                Opcode.MODULO,
            ):
                right = pop(instruction)
                left = pop(instruction)
                if opcode is Opcode.ADD and type(left) is type(right) is str:
                    if len(left) + len(right) > self.max_string_length:
                        raise fault(
                            f"String length limit ({self.max_string_length}) exceeded.",
                            instruction,
                        )
                    push(left + right, instruction)
                else:
                    if type(left) not in (int, float) or type(left) is not type(right):
                        raise fault(
                            f"{opcode.value} requires matching numeric operands.",
                            instruction,
                        )
                    if type(left) is int:
                        left_bits = left.bit_length()
                        right_bits = right.bit_length()
                        if opcode in (Opcode.ADD, Opcode.SUBTRACT):
                            estimated_bits = max(left_bits, right_bits) + 1
                        elif opcode is Opcode.MULTIPLY and left and right:
                            estimated_bits = left_bits + right_bits
                        else:
                            estimated_bits = max(left_bits, right_bits)
                        if estimated_bits > self.max_integer_bits:
                            raise fault(
                                f"Integer bit limit ({self.max_integer_bits}) exceeded.",
                                instruction,
                            )
                    if opcode is Opcode.ADD:
                        value = left + right
                    elif opcode is Opcode.SUBTRACT:
                        value = left - right
                    elif opcode is Opcode.MULTIPLY:
                        value = left * right
                    elif opcode is Opcode.DIVIDE:
                        if right == 0:
                            raise fault("Division by zero.", instruction)
                        try:
                            value = left / right
                        except OverflowError:
                            raise fault("Numeric result is outside the supported range.", instruction) from None
                    else:
                        if type(left) is not int:
                            raise fault("MODULO requires integer operands.", instruction)
                        if right == 0:
                            raise fault("Modulo by zero.", instruction)
                        value = left % right
                    push(value, instruction)
            elif opcode in (
                Opcode.EQUAL,
                Opcode.NOT_EQUAL,
                Opcode.LESS,
                Opcode.LESS_EQUAL,
                Opcode.GREATER,
                Opcode.GREATER_EQUAL,
            ):
                right = pop(instruction)
                left = pop(instruction)
                if type(left) is not type(right):
                    raise fault(
                        f"{opcode.value} requires operands of the same type.",
                        instruction,
                    )
                if opcode in (
                    Opcode.LESS,
                    Opcode.LESS_EQUAL,
                    Opcode.GREATER,
                    Opcode.GREATER_EQUAL,
                ) and type(left) not in (int, float):
                    raise fault(
                        f"{opcode.value} requires numeric operands.",
                        instruction,
                    )
                if opcode is Opcode.EQUAL:
                    value = left == right
                elif opcode is Opcode.NOT_EQUAL:
                    value = left != right
                elif opcode is Opcode.LESS:
                    value = left < right
                elif opcode is Opcode.LESS_EQUAL:
                    value = left <= right
                elif opcode is Opcode.GREATER:
                    value = left > right
                else:
                    value = left >= right
                push(value, instruction)
            elif opcode in (Opcode.AND, Opcode.OR):
                right = pop(instruction)
                left = pop(instruction)
                if type(left) is not bool or type(right) is not bool:
                    raise fault(
                        f"{opcode.value} requires boolean operands.",
                        instruction,
                    )
                push((left and right) if opcode is Opcode.AND else (left or right), instruction)
            elif opcode is Opcode.PRINT:
                rendered = format_value(pop(instruction))
                if output_chars + len(rendered) > self.max_output_chars:
                    raise fault(
                        f"Captured output limit ({self.max_output_chars} characters) exceeded.",
                        instruction,
                    )
                output.append(rendered)
                output_chars += len(rendered)
            elif opcode is Opcode.JUMP:
                next_ip = instruction.operand
            elif opcode is Opcode.JUMP_IF_FALSE:
                condition = pop(instruction)
                if type(condition) is not bool:
                    raise fault("JUMP_IF_FALSE requires a boolean condition.", instruction)
                if not condition:
                    next_ip = instruction.operand
            elif opcode is Opcode.CALL:
                target = functions.get(instruction.operand)
                if target is None and instruction.operand in BUILTIN_ARITIES:
                    name = instruction.operand
                    arity = BUILTIN_ARITIES[name]
                    if len(stack) < arity:
                        raise fault(f"Not enough arguments for standard-library function '{name}'.", instruction)
                    args = stack[-arity:] if arity else []
                    if arity:
                        del stack[-arity:]

                    def require_builtin_type(index: int, expected: str) -> None:
                        if index >= len(args) or not self._matches_type(args[index], expected):
                            raise fault(
                                f"Standard-library function '{name}' expects argument {index + 1} to be {expected}.",
                                instruction,
                            )

                    if name in ("abs", "sqrt", "round", "to_int", "to_float"):
                        if type(args[0]) not in (int, float):
                            raise fault(f"'{name}' expects a numeric argument.", instruction)
                    elif name in ("min", "max"):
                        if (
                            type(args[0]) not in (int, float)
                            or type(args[1]) is not type(args[0])
                        ):
                            raise fault(f"'{name}' expects two matching numeric arguments.", instruction)
                    elif name in ("contains", "starts_with", "ends_with"):
                        require_builtin_type(0, "string")
                        require_builtin_type(1, "string")
                    elif name == "substring":
                        require_builtin_type(0, "string")
                        require_builtin_type(1, "int")
                        require_builtin_type(2, "int")
                    elif name in ("read_text", "file_exists"):
                        require_builtin_type(0, "string")
                    elif name == "write_text":
                        require_builtin_type(0, "string")
                        require_builtin_type(1, "string")

                    try:
                        if name == "abs":
                            value = abs(args[0])
                        elif name == "min":
                            value = min(args)
                        elif name == "max":
                            value = max(args)
                        elif name == "sqrt":
                            value = math.sqrt(args[0])
                        elif name == "round":
                            value = round(args[0])
                        elif name == "to_int":
                            value = int(args[0])
                        elif name == "to_float":
                            value = float(args[0])
                        elif name == "to_string":
                            value = format_value(args[0])
                        elif name == "contains":
                            value = args[1] in args[0]
                        elif name == "starts_with":
                            value = args[0].startswith(args[1])
                        elif name == "ends_with":
                            value = args[0].endswith(args[1])
                        elif name == "substring":
                            source, start, end = args
                            if start < 0 or end < start or end > len(source):
                                raise fault("substring indices are outside the string bounds.", instruction)
                            value = source[start:end]
                        elif name in FILE_IO_FUNCTIONS:
                            target_path = resolve_file_path(args[0], instruction)
                            if name == "file_exists":
                                value = target_path.is_file()
                            elif name == "read_text":
                                try:
                                    if target_path.stat().st_size > self.max_file_bytes:
                                        raise fault(f"File exceeds the configured read limit ({self.max_file_bytes} bytes).", instruction)
                                    with target_path.open("rb") as handle:
                                        payload = handle.read(self.max_file_bytes + 1)
                                    if len(payload) > self.max_file_bytes:
                                        raise fault(f"File exceeds the configured read limit ({self.max_file_bytes} bytes).", instruction)
                                    try:
                                        value = payload.decode("utf-8")
                                    except UnicodeDecodeError:
                                        raise fault("File is not valid UTF-8 text.", instruction) from None
                                except UnicodeDecodeError:
                                    raise fault("File is not valid UTF-8 text.", instruction) from None
                                except OSError as exc:
                                    raise fault(f"Could not read file: {exc.strerror or exc}.", instruction) from None
                            else:
                                content = args[1]
                                encoded = content.encode("utf-8")
                                if len(encoded) > self.max_file_bytes:
                                    raise fault(f"File exceeds the configured write limit ({self.max_file_bytes} bytes).", instruction)
                                if not target_path.parent.is_dir():
                                    raise fault("Parent directory for file write does not exist.", instruction)
                                temporary_path = None
                                try:
                                    with tempfile.NamedTemporaryFile(
                                        mode="wb",
                                        dir=target_path.parent,
                                        prefix=".rifai-",
                                        delete=False,
                                    ) as handle:
                                        temporary_path = Path(handle.name)
                                        handle.write(encoded)
                                        handle.flush()
                                        os.fsync(handle.fileno())
                                    os.replace(temporary_path, target_path)
                                    value = True
                                except OSError as exc:
                                    if temporary_path is not None:
                                        try:
                                            temporary_path.unlink(missing_ok=True)
                                        except OSError:
                                            pass
                                    raise fault(f"Could not write file: {exc.strerror or exc}.", instruction) from None
                        else:
                            raise fault(f"Unknown standard-library function '{name}'.", instruction)
                    except (ArithmeticError, TypeError, ValueError, OverflowError) as exc:
                        raise fault(f"Standard-library function '{name}' failed: {exc}.", instruction) from None
                    push(value, instruction)
                    frame.ip = next_ip
                    continue
                if target is None:
                    raise fault(f"Undefined function '{instruction.operand}'.", instruction)
                if len(frames) >= self.max_call_depth:
                    raise fault(
                        f"Call stack limit ({self.max_call_depth}) exceeded.",
                        instruction,
                    )
                arity = target.arity
                if len(stack) < arity:
                    raise fault("Not enough arguments on the operand stack.", instruction)
                args = stack[-arity:] if arity else []
                if arity:
                    del stack[-arity:]
                for index, (argument, expected) in enumerate(
                    zip(args, target.parameter_types), start=1
                ):
                    if not self._matches_type(argument, expected):
                        raise fault(
                            f"Argument {index} of '{target.name}' expected '{expected}'.",
                            instruction,
                        )
                local_values: list[RuntimeValue | object] = [
                    _UNINITIALIZED for _ in range(target.chunk.local_count)
                ]
                for index, argument in enumerate(args):
                    local_values[index] = argument
                frame.ip = next_ip
                frames.append(
                    _CallFrame(
                        chunk=target.chunk,
                        name=target.name,
                        locals=local_values,
                        ip=0,
                        stack_base=len(stack),
                        returns_value=target.returns_value,
                    )
                )
                continue
            elif opcode is Opcode.RETURN:
                if frame.is_main:
                    raise fault("RETURN cannot execute in the main chunk.", instruction)
                returned: RuntimeValue | None = None
                if frame.returns_value:
                    returned = pop(instruction)
                    function_meta = functions[frame.name]
                    if not self._matches_type(returned, function_meta.return_type):
                        raise fault(
                            f"Function '{frame.name}' returned a value with the wrong type.",
                            instruction,
                        )
                expected_stack_size = frame.stack_base + (1 if frame.returns_value else 0)
                if len(stack) + (1 if frame.returns_value else 0) != expected_stack_size:
                    raise fault(
                        f"Function '{frame.name}' left an invalid operand stack state.",
                        instruction,
                    )
                frames.pop()
                if returned is not None:
                    if not frames:
                        raise fault("A function returned without a caller.", instruction)
                    push(returned, instruction)
                continue
            elif opcode is Opcode.HALT:
                if not frame.is_main:
                    raise fault("HALT cannot execute inside a function.", instruction)
                break
            else:
                raise fault(f"Unsupported opcode {opcode!r}.", instruction)

            frame.ip = next_ip

        return ExecutionResult(
            output=tuple(output),
            globals=globals_,
            instructions_executed=executed,
            final_stack=tuple(stack),
        )
