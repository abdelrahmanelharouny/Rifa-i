"""Human-readable disassembly of Rifa'i bytecode modules."""

from __future__ import annotations

from rifai.bytecode.instructions import Instruction, Opcode
from rifai.bytecode.module import BytecodeModule


def disassemble(module: BytecodeModule) -> str:
    """Return a stable listing; malformed references are rendered safely."""
    lines = [
        f"Rifa'i Bytecode v{module.format_version}",
        f"Source: {module.source_name or '<unknown>'}",
        f"Main chunk: {module.main.name}",
        f"Locals: {module.main.local_count}",
        "",
        "Constants:",
    ]
    if module.constants:
        for index, value in enumerate(module.constants):
            lines.append(f"  [{index:04d}] {type(value).__name__}: {value!r}")
    else:
        lines.append("  <empty>")

    lines.extend(["", "Instructions:", ""])
    for index, instruction in enumerate(module.main.instructions):
        if not isinstance(instruction, Instruction):
            lines.append(f"  {index:04d}  <invalid instruction: {instruction!r}>")
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
                    and 0 <= instruction.operand < len(module.constants)
                ):
                    operand += f"  ; {module.constants[instruction.operand]!r}"
                else:
                    operand += "  ; invalid constant index"
        location = ""
        if instruction.location is not None:
            location = (
                f"  ; source {instruction.location.line}:"
                f"{instruction.location.column}"
            )
        lines.append(f"  {index:04d}  {opcode_name:<16}{operand}{location}")
    return "\n".join(lines)
