"""A verified stack-based bytecode interpreter for Rifa'i."""

from __future__ import annotations

from collections.abc import Mapping

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


class VirtualMachine:
    """Execute version 1 Rifa'i bytecode in an isolated VM state."""

    def __init__(
        self,
        *,
        max_steps: int = 1_000_000,
        max_stack_depth: int = 100_000,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")
        if max_stack_depth < 1:
            raise ValueError("max_stack_depth must be at least 1.")
        self.max_steps = max_steps
        self.max_stack_depth = max_stack_depth

    def execute(
        self,
        module: BytecodeModule,
        *,
        initial_globals: Mapping[str, RuntimeValue] | None = None,
    ) -> ExecutionResult:
        """Verify and execute a module, returning captured output and state."""
        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            raise BytecodeValidationError(validation.diagnostics)

        stack: list[RuntimeValue] = []
        locals_: list[RuntimeValue | object] = [
            _UNINITIALIZED for _ in range(module.main.local_count)
        ]
        globals_: dict[str, RuntimeValue] = dict(initial_globals or {})
        output: list[str] = []
        instructions = module.main.instructions
        ip = 0
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
            if len(stack) >= self.max_stack_depth:
                raise fault(
                    f"Operand stack limit ({self.max_stack_depth}) exceeded.",
                    instruction,
                )
            stack.append(value)

        while True:
            if executed >= self.max_steps:
                current = instructions[ip]
                raise fault(
                    f"Instruction limit ({self.max_steps}) exceeded.",
                    current,
                )
            instruction = instructions[ip]
            opcode = instruction.opcode
            executed += 1
            next_ip = ip + 1

            if opcode is Opcode.CONSTANT:
                push(module.constants[instruction.operand], instruction)
            elif opcode is Opcode.POP:
                pop(instruction)
            elif opcode is Opcode.DUP:
                if not stack:
                    raise fault("DUP requires a value on the operand stack.", instruction)
                push(stack[-1], instruction)
            elif opcode is Opcode.LOAD_LOCAL:
                value = locals_[instruction.operand]
                if value is _UNINITIALIZED:
                    raise fault(
                        f"Local slot {instruction.operand} was read before initialization.",
                        instruction,
                    )
                push(value, instruction)
            elif opcode is Opcode.STORE_LOCAL:
                locals_[instruction.operand] = pop(instruction)
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
            elif opcode in (Opcode.ADD, Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE, Opcode.MODULO):
                right = pop(instruction)
                left = pop(instruction)
                if opcode is Opcode.ADD and type(left) is type(right) is str:
                    push(left + right, instruction)
                    ip = next_ip
                    continue
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
                if opcode in (Opcode.LESS, Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL):
                    if type(left) not in (int, float):
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
                    raise fault(f"{opcode.value} requires boolean operands.", instruction)
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
            elif opcode is Opcode.HALT:
                break
            else:  # Defensive guard in case a future opcode reaches this VM.
                raise fault(f"Unsupported opcode {opcode!r}.", instruction)

            ip = next_ip

        return ExecutionResult(
            output=tuple(output),
            globals=globals_,
            instructions_executed=executed,
            final_stack=tuple(stack),
        )
