"""Structural and control-flow verification for Rifa'i bytecode."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import (
    Instruction,
    Opcode,
    expected_operand_kind,
    stack_delta,
    stack_requirement,
)
from rifai.bytecode.module import (
    BytecodeModule,
    FORMAT_VERSION,
    LEGACY_FORMAT_VERSION,
    is_constant,
)
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase

_ALLOWED_VALUE_TYPES = frozenset({"int", "float", "bool", "string"})
_ALLOWED_RETURN_TYPES = _ALLOWED_VALUE_TYPES | {"void"}


@dataclass(frozen=True, slots=True)
class BytecodeValidationResult:
    """Result of validating a bytecode module."""

    diagnostics: tuple[Diagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


class BytecodeVerifier:
    """Validate module structure and operand-stack data flow before execution."""

    def verify(self, module: BytecodeModule) -> BytecodeValidationResult:
        diagnostics: list[Diagnostic] = []

        def report(message: str, instruction: Instruction | None = None) -> None:
            location = instruction.location if instruction is not None else None
            diagnostics.append(
                Diagnostic(
                    phase=DiagnosticPhase.BYTECODE,
                    message=message,
                    line=location.line if location else 1,
                    column=location.column if location else 1,
                    start_offset=location.start_offset if location else None,
                    end_offset=location.end_offset if location else None,
                )
            )

        if not isinstance(module, BytecodeModule):
            report("Expected a BytecodeModule instance.")
            return BytecodeValidationResult(tuple(diagnostics))
        if type(module.format_version) is not int or module.format_version not in (
            LEGACY_FORMAT_VERSION,
            FORMAT_VERSION,
        ):
            report(f"Unsupported bytecode version {module.format_version!r}.")
        if module.source_name is not None and not isinstance(module.source_name, str):
            report("Module source_name must be a string or null.")
        if not isinstance(module.constants, tuple):
            report("Module constants must be an immutable tuple.")
        else:
            for index, value in enumerate(module.constants):
                if not is_constant(value):
                    report(f"Constant pool entry {index} has an unsupported value.")

        if not isinstance(module.main, CodeChunk):
            report("Module main must be a CodeChunk.")
            return BytecodeValidationResult(tuple(diagnostics))
        if not isinstance(module.functions, tuple):
            report("Module functions must be an immutable tuple.")
            return BytecodeValidationResult(tuple(diagnostics))
        if module.format_version == LEGACY_FORMAT_VERSION and module.functions:
            report("Version 1 bytecode cannot contain function chunks.")

        function_by_name: dict[str, BytecodeFunction] = {}
        for function in module.functions:
            if not isinstance(function, BytecodeFunction):
                report("Function table contains an invalid entry.")
                continue
            if not isinstance(function.name, str) or not function.name:
                report("Function names must be non-empty strings.")
                continue
            if function.name in function_by_name:
                report(f"Duplicate function '{function.name}' in bytecode module.")
                continue
            function_by_name[function.name] = function
            if not isinstance(function.chunk, CodeChunk):
                report(f"Function '{function.name}' has an invalid code chunk.")
                continue
            if function.chunk.name != function.name:
                report(f"Function '{function.name}' chunk name does not match its metadata.")
            if not isinstance(function.parameter_types, tuple) or any(
                not isinstance(item, str) or item not in _ALLOWED_VALUE_TYPES
                for item in function.parameter_types
            ):
                report(f"Function '{function.name}' has invalid parameter types.")
            if (
                not isinstance(function.return_type, str)
                or function.return_type not in _ALLOWED_RETURN_TYPES
            ):
                report(f"Function '{function.name}' has an invalid return type.")
            if function.chunk.arity != function.arity:
                report(f"Function '{function.name}' arity does not match its signature.")

        chunks: list[tuple[str, CodeChunk, str | None, bool]] = [
            ("<main>", module.main, None, True)
        ]
        for function in module.functions:
            if isinstance(function, BytecodeFunction) and isinstance(function.chunk, CodeChunk):
                chunks.append((function.name, function.chunk, function.return_type, False))

        for chunk_name, chunk, return_type, is_main in chunks:
            if not isinstance(chunk.name, str) or not chunk.name:
                report(f"Code chunk '{chunk_name}' must have a non-empty name.")
            if type(chunk.arity) is not int or chunk.arity < 0:
                report(f"Code chunk '{chunk_name}' arity must be non-negative.")
            if type(chunk.local_count) is not int or chunk.local_count < 0:
                report(f"Code chunk '{chunk_name}' local_count must be non-negative.")
            elif type(chunk.arity) is int and chunk.arity > chunk.local_count:
                report(f"Code chunk '{chunk_name}' arity cannot exceed local_count.")

            instructions = chunk.instructions
            if not isinstance(instructions, tuple):
                report(f"Code chunk '{chunk_name}' instructions must be a tuple.")
                continue
            if not instructions:
                report(f"Code chunk '{chunk_name}' is empty.")
                continue

            if is_main:
                if (
                    not isinstance(instructions[-1], Instruction)
                    or instructions[-1].opcode is not Opcode.HALT
                ):
                    report("The main chunk must end with HALT.")
                halt_positions = [
                    index for index, item in enumerate(instructions)
                    if isinstance(item, Instruction) and item.opcode is Opcode.HALT
                ]
                if len(halt_positions) != 1 or (
                    halt_positions and halt_positions[0] != len(instructions) - 1
                ):
                    report("The main chunk must contain exactly one final HALT.")
            elif not any(
                isinstance(item, Instruction) and item.opcode is Opcode.RETURN
                for item in instructions
            ):
                report(f"Function '{chunk_name}' has no RETURN instruction.")

            structurally_valid: set[int] = set()
            for index, instruction in enumerate(instructions):
                if not isinstance(instruction, Instruction):
                    report(f"Instruction {index} in '{chunk_name}' is invalid.")
                    continue
                if not isinstance(instruction.opcode, Opcode):
                    report(f"Instruction {index} in '{chunk_name}' has an unknown opcode.")
                    continue

                opcode = instruction.opcode
                kind = expected_operand_kind(opcode)
                operand = instruction.operand
                if kind == "integer" and type(operand) is not int:
                    report(f"{opcode.value} at instruction {index} requires an integer operand.", instruction)
                    continue
                if kind == "string" and (
                    not isinstance(operand, str) or not operand
                ):
                    report(f"{opcode.value} at instruction {index} requires a non-empty string operand.", instruction)
                    continue
                if kind == "none" and operand is not None:
                    report(f"{opcode.value} at instruction {index} does not accept an operand.", instruction)
                    continue

                if opcode is Opcode.CONSTANT:
                    if not isinstance(module.constants, tuple) or not 0 <= operand < len(module.constants):
                        report(f"Constant index {operand} is out of range at instruction {index}.", instruction)
                        continue
                elif opcode in (Opcode.LOAD_LOCAL, Opcode.STORE_LOCAL):
                    if type(chunk.local_count) is not int or not 0 <= operand < chunk.local_count:
                        report(f"Local slot {operand} is out of range at instruction {index}.", instruction)
                        continue
                elif opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
                    if not 0 <= operand < len(instructions):
                        report(f"Jump target {operand} is out of range at instruction {index}.", instruction)
                        continue
                elif opcode is Opcode.CALL:
                    if module.format_version < FORMAT_VERSION or operand not in function_by_name:
                        report(f"Call target '{operand}' does not exist in this bytecode module.", instruction)
                        continue
                elif opcode is Opcode.HALT and not is_main:
                    report("HALT is only valid in the main chunk.", instruction)
                    continue
                elif opcode is Opcode.RETURN and is_main:
                    report("RETURN is only valid inside a function chunk.", instruction)
                    continue
                structurally_valid.add(index)

            if 0 not in structurally_valid:
                continue

            depths: dict[int, int] = {0: 0}
            queue: deque[int] = deque([0])
            while queue:
                index = queue.popleft()
                if index not in structurally_valid:
                    continue
                instruction = instructions[index]
                opcode = instruction.opcode
                before = depths[index]

                if opcode is Opcode.CALL:
                    target = function_by_name.get(instruction.operand)
                    required = target.arity if target is not None else 0
                    delta = -required + (
                        1 if target is not None and target.returns_value else 0
                    )
                elif opcode is Opcode.RETURN:
                    required = 1 if return_type != "void" else 0
                    delta = 0
                else:
                    required = stack_requirement(opcode)
                    delta = stack_delta(opcode)

                if before < required:
                    report(
                        f"Stack underflow in '{chunk_name}' at instruction {index} "
                        f"({opcode.value}): requires {required}, has {before}.",
                        instruction,
                    )
                    continue

                if opcode is Opcode.RETURN:
                    expected_depth = 1 if return_type != "void" else 0
                    if before != expected_depth:
                        report(
                            f"RETURN in '{chunk_name}' requires stack depth {expected_depth}, "
                            f"found {before}.",
                            instruction,
                        )
                    successors: tuple[int, ...] = ()
                elif opcode is Opcode.HALT:
                    if before != 0:
                        report(f"Stack must be empty at HALT; found depth {before}.", instruction)
                    successors = ()
                elif opcode is Opcode.JUMP:
                    successors = (instruction.operand,)
                elif opcode is Opcode.JUMP_IF_FALSE:
                    successors = (instruction.operand, index + 1)
                else:
                    successors = (index + 1,)

                after = before + delta
                for successor in successors:
                    if successor >= len(instructions):
                        report(f"Execution can fall off the end of '{chunk_name}' after instruction {index}.", instruction)
                        continue
                    if successor not in structurally_valid:
                        continue
                    known = depths.get(successor)
                    if known is None:
                        depths[successor] = after
                        queue.append(successor)
                    elif known != after:
                        report(
                            f"Inconsistent stack depth at control-flow merge in '{chunk_name}' "
                            f"instruction {successor}: {known} versus {after}.",
                            instructions[successor],
                        )

        return BytecodeValidationResult(tuple(diagnostics))
