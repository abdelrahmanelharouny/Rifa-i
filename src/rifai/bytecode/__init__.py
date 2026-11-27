"""Bytecode models, serialization, verification, and inspection for Rifa'i."""

from rifai.bytecode.chunk import CodeChunk
from rifai.bytecode.disassembler import disassemble
from rifai.bytecode.instructions import Instruction, Opcode, SourceLocation
from rifai.bytecode.module import BytecodeModule, Constant, FORMAT_VERSION
from rifai.bytecode.serializer import BytecodeFormatError, BytecodeSerializer
from rifai.bytecode.verifier import BytecodeValidationResult, BytecodeVerifier

__all__ = [
    "BytecodeFormatError",
    "BytecodeModule",
    "BytecodeSerializer",
    "BytecodeValidationResult",
    "BytecodeVerifier",
    "CodeChunk",
    "Constant",
    "FORMAT_VERSION",
    "Instruction",
    "Opcode",
    "SourceLocation",
    "disassemble",
]
