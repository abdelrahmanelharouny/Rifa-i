"""Human-readable disassembly of Rifa'i bytecode modules."""

from __future__ import annotations

from rifai.bytecode.instructions import Opcode
from rifai.bytecode.module import BytecodeModule


def disassemble(module: BytecodeModule) -> str:
    """Return a stable, readable listing of a bytecode module."""
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
        operand = ""
        if instruction.operand is not None:
            operand = f" {instruction.operand}"
            if instruction.opcode is Opcode.CONSTANT:
                value = module.constants[instruction.operand]
                operand += f"  ; {value!r}"
        location = ""
        if instruction.location is not None:
            location = (
                f"  ; source {instruction.location.line}:"
                f"{instruction.location.column}"
            )
        lines.append(
            f"  {index:04d}  {instruction.opcode.value:<16}{operand}{location}"
        )
    return "\n".join(lines)
