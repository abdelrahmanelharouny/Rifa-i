"""A verified stack-based bytecode interpreter with function call frames."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode
from rifai.bytecode.module import BytecodeModule
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.vm.runtime import (
    BytecodeValidationError,
    ExecutionResult,
    VMRuntimeError,
    format_value,
)

_UNINITIALIZED = object()
RuntimeValue = int | float | bool | str


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
    ) -> None:
        limits = {
            "max_steps": max_steps,
            "max_stack_depth": max_stack_depth,
            "max_call_depth": max_call_depth,
            "max_string_length": max_string_length,
            "max_output_chars": max_output_chars,
            "max_integer_bits": max_integer_bits,
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

    @staticmethod
    def _matches_type(value: RuntimeValue, type_name: str) -> bool:
        if type_name == "bool":
            return type(value) is bool
        if type_name == "int":
            return type(value) is int
        if type_name == "float":
            return type(value) is float
        if type_name == "string":
            return type(value) is str
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
            if type(value) not in (int, float, bool, str):
                raise ValueError(f"Initial global {name!r} has an unsupported value.")
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
