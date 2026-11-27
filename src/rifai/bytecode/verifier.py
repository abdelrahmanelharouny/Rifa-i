"""Structural and control-flow verification for Rifa'i bytecode."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rifai.bytecode.chunk import CodeChunk
from rifai.bytecode.instructions import (
    Instruction,
    Opcode,
    expected_operand_kind,
    stack_delta,
    stack_requirement,
)
from rifai.bytecode.module import BytecodeModule, FORMAT_VERSION, is_constant
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase


@dataclass(frozen=True, slots=True)
class BytecodeValidationResult:
    """Result of validating a bytecode module."""

    diagnostics: tuple[Diagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


class BytecodeVerifier:
    """Validate bytecode before it is loaded or executed."""

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

        if type(module.format_version) is not int or module.format_version != FORMAT_VERSION:
            report(
                f"Unsupported bytecode version {module.format_version}; "
                f"supported version is {FORMAT_VERSION}."
            )
        if module.source_name is not None and not isinstance(module.source_name, str):
            report("Module source_name must be a string or null.")
        if not isinstance(module.constants, tuple):
            report("Module constants must be an immutable tuple.")
        else:
            for index, value in enumerate(module.constants):
                if not is_constant(value):
                    report(f"Constant pool entry {index} has an unsupported value.")

        chunk = module.main
        if not isinstance(chunk, CodeChunk):
            report("Module main must be a CodeChunk.")
            return BytecodeValidationResult(tuple(diagnostics))

        if not isinstance(chunk.name, str) or not chunk.name:
            report("Main chunk must have a non-empty name.")
        if type(chunk.arity) is not int or chunk.arity < 0:
            report("Chunk arity must be a non-negative integer.")
        if type(chunk.local_count) is not int or chunk.local_count < 0:
            report("Chunk local_count must be a non-negative integer.")
        elif type(chunk.arity) is int and chunk.arity > chunk.local_count:
            report("Chunk arity cannot exceed local_count.")

        instructions = chunk.instructions
        if not isinstance(instructions, tuple):
            report("Chunk instructions must be an immutable tuple.")
            return BytecodeValidationResult(tuple(diagnostics))
        if not instructions:
            report("Main chunk contains no instructions.")
            return BytecodeValidationResult(tuple(diagnostics))

        if not isinstance(instructions[-1], Instruction) or instructions[-1].opcode is not Opcode.HALT:
            report("The main chunk must end with HALT.")
        halt_positions = [
            index for index, item in enumerate(instructions)
            if isinstance(item, Instruction) and item.opcode is Opcode.HALT
        ]
        if len(halt_positions) != 1 or (halt_positions and halt_positions[0] != len(instructions) - 1):
            report("The main chunk must contain exactly one HALT, as its final instruction.")

        structurally_valid: set[int] = set()
        for index, instruction in enumerate(instructions):
            if not isinstance(instruction, Instruction):
                report(f"Instruction {index} is not an Instruction instance.")
                continue
            if not isinstance(instruction.opcode, Opcode):
                report(f"Instruction {index} has an unknown opcode.")
                continue

            kind = expected_operand_kind(instruction.opcode)
            operand = instruction.operand
            if kind == "integer":
                if type(operand) is not int:
                    report(
                        f"{instruction.opcode.value} at instruction {index} "
                        "requires an integer operand.",
                        instruction,
                    )
                    continue
            elif kind == "string":
                if not isinstance(operand, str) or not operand:
                    report(
                        f"{instruction.opcode.value} at instruction {index} "
                        "requires a non-empty string operand.",
                        instruction,
                    )
                    continue
            elif operand is not None:
                report(
                    f"{instruction.opcode.value} at instruction {index} "
                    "does not accept an operand.",
                    instruction,
                )
                continue

            if instruction.opcode is Opcode.CONSTANT:
                if not isinstance(module.constants, tuple) or not 0 <= operand < len(module.constants):
                    report(
                        f"Constant index {operand} is out of range at instruction {index}.",
                        instruction,
                    )
                    continue
            elif instruction.opcode in (Opcode.LOAD_LOCAL, Opcode.STORE_LOCAL):
                if type(chunk.local_count) is not int or not 0 <= operand < chunk.local_count:
                    report(
                        f"Local slot {operand} is out of range at instruction {index}.",
                        instruction,
                    )
                    continue
            elif instruction.opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
                if not 0 <= operand < len(instructions):
                    report(
                        f"Jump target {operand} is out of range at instruction {index}.",
                        instruction,
                    )
                    continue
            structurally_valid.add(index)

        # Work-list data-flow checks stack underflow and stack-height consistency
        # at control-flow merge points, including conditional branches.
        if 0 in structurally_valid:
            depths: dict[int, int] = {0: 0}
            queue: deque[int] = deque([0])
            while queue:
                index = queue.popleft()
                if index not in structurally_valid:
                    continue
                instruction = instructions[index]
                opcode = instruction.opcode
                before = depths[index]
                required = stack_requirement(opcode)
                if before < required:
                    report(
                        f"Stack underflow at instruction {index} ({opcode.value}): "
                        f"requires {required}, has {before}.",
                        instruction,
                    )
                    continue

                after = before + stack_delta(opcode)
                if opcode is Opcode.HALT:
                    if after != 0:
                        report(
                            f"Stack must be empty at HALT; found depth {after}.",
                            instruction,
                        )
                    successors: tuple[int, ...] = ()
                elif opcode is Opcode.JUMP:
                    successors = (instruction.operand,)
                elif opcode is Opcode.JUMP_IF_FALSE:
                    successors = (instruction.operand, index + 1)
                else:
                    successors = (index + 1,)

                for successor in successors:
                    if successor >= len(instructions):
                        report(
                            f"Execution can fall off the end after instruction {index}.",
                            instruction,
                        )
                        continue
                    if successor not in structurally_valid:
                        continue
                    known = depths.get(successor)
                    if known is None:
                        depths[successor] = after
                        queue.append(successor)
                    elif known != after:
                        report(
                            f"Inconsistent stack depth at control-flow merge "
                            f"instruction {successor}: {known} versus {after}.",
                            instructions[successor],
                        )

        return BytecodeValidationResult(tuple(diagnostics))
