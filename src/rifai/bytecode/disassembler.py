"""Human-readable disassembly of Rifa'i bytecode modules."""

from __future__ import annotations

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode
from rifai.bytecode.module import BytecodeModule


def _disassemble_chunk(chunk: CodeChunk, constants: tuple[object, ...]) -> list[str]:
    lines = [
        f"Chunk: {chunk.name}",
        f"  Arity: {chunk.arity}",
        f"  Locals: {chunk.local_count}",
        "  Instructions:",
    ]
    for index, instruction in enumerate(chunk.instructions):
        if not isinstance(instruction, Instruction):
            lines.append(f"    {index:04d}  <invalid instruction: {instruction!r}>")
            continue
        opcode_name = (
            instruction.opcode.value
            if isinstance(instruction.opcode, Opcode)
            else repr(instruction.opcode)
        )
        operand = ""
        if instruction.operand is not None:
            operand = f" {instruction.operand}"
            if instruction.opcode is Opcode.CONSTANT:
                if (
                    type(instruction.operand) is int
                    and 0 <= instruction.operand < len(constants)
                ):
                    operand += f"  ; {constants[instruction.operand]!r}"
                else:
                    operand += "  ; invalid constant index"
        location = ""
        if instruction.location is not None:
            location = (
                f"  ; source {instruction.location.line}:"
                f"{instruction.location.column}"
            )
        lines.append(f"    {index:04d}  {opcode_name:<16}{operand}{location}")
    return lines


def disassemble(module: BytecodeModule) -> str:
    """Return a stable, readable listing of constants, main, and function chunks."""
    lines = [
        f"Rifa'i Bytecode v{module.format_version}",
        f"Source: {module.source_name or '<unknown>'}",
        "",
        "Constants:",
    ]
    if module.constants:
        for index, value in enumerate(module.constants):
            lines.append(f"  [{index:04d}] {type(value).__name__}: {value!r}")
    else:
        lines.append("  <empty>")

    lines.extend(["", *_disassemble_chunk(module.main, module.constants)])
    for function in module.functions:
        if not isinstance(function, BytecodeFunction):
            lines.extend(["", f"Function: <invalid metadata {function!r}>"])
            continue
        params = ", ".join(function.parameter_types)
        lines.extend(
            [
                "",
                f"Function: {function.name}({params}) -> {function.return_type}",
                *_disassemble_chunk(function.chunk, module.constants),
            ]
        )
    return "\n".join(lines)
