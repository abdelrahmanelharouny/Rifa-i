"""A verified stack-based bytecode interpreter with function call frames."""

from __future__ import annotations

from collections.abc import Mapping
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


class VirtualMachine:
    """Execute verified Rifa'i bytecode with isolated locals and recursive calls."""

    def __init__(
        self,
        *,
        max_steps: int = 1_000_000,
        max_stack_depth: int = 100_000,
        max_call_depth: int = 1_024,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")
        if max_stack_depth < 1:
            raise ValueError("max_stack_depth must be at least 1.")
        if max_call_depth < 1:
            raise ValueError("max_call_depth must be at least 1.")
        self.max_steps = max_steps
        self.max_stack_depth = max_stack_depth
        self.max_call_depth = max_call_depth

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
    ) -> ExecutionResult:
        """Verify and execute a module, returning captured output and global state."""
        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            raise BytecodeValidationError(validation.diagnostics)

        globals_: dict[str, RuntimeValue] = {}
        for name, value in (initial_globals or {}).items():
            if not isinstance(name, str) or not name:
                raise ValueError("Initial global names must be non-empty strings.")
            if type(value) not in (int, float, bool, str):
                raise ValueError(f"Initial global {name!r} has an unsupported value.")
            if type(value) is float and not math.isfinite(value):
                raise ValueError(f"Initial global {name!r} must be a finite float.")
            globals_[name] = value

        functions: dict[str, BytecodeFunction] = {
            function.name: function for function in module.functions
        }
        stack: list[RuntimeValue] = []
        output: list[str] = []
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
                    push(left + right, instruction)
                else:
                    if type(left) not in (int, float) or type(left) is not type(right):
                        raise fault(
                            f"{opcode.value} requires matching numeric operands.",
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
                        value = left / right
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
                output.append(format_value(pop(instruction)))
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
