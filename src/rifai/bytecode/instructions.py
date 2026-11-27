"""Instruction definitions for the Rifa'i stack-based bytecode."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Opcode(str, Enum):
    """Version 1 bytecode instructions supported by the Rifa'i VM."""

    CONSTANT = "CONSTANT"
    POP = "POP"
    DUP = "DUP"

    LOAD_LOCAL = "LOAD_LOCAL"
    STORE_LOCAL = "STORE_LOCAL"
    LOAD_GLOBAL = "LOAD_GLOBAL"
    STORE_GLOBAL = "STORE_GLOBAL"

    NEGATE = "NEGATE"
    NOT = "NOT"

    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MULTIPLY = "MULTIPLY"
    DIVIDE = "DIVIDE"
    MODULO = "MODULO"

    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    LESS = "LESS"
    LESS_EQUAL = "LESS_EQUAL"
    GREATER = "GREATER"
    GREATER_EQUAL = "GREATER_EQUAL"

    AND = "AND"
    OR = "OR"

    PRINT = "PRINT"
    JUMP = "JUMP"
    JUMP_IF_FALSE = "JUMP_IF_FALSE"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Optional source-map location attached to a bytecode instruction."""

    line: int
    column: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class Instruction:
    """One opcode and its optional operand and original source location."""

    opcode: Opcode
    operand: int | str | None = None
    location: SourceLocation | None = None


# Operand contracts are intentionally explicit so the verifier, serializer,
# disassembler, and VM agree on the bytecode representation.
_INTEGER_OPERAND_OPCODES = frozenset(
    {
        Opcode.CONSTANT,
        Opcode.LOAD_LOCAL,
        Opcode.STORE_LOCAL,
        Opcode.JUMP,
        Opcode.JUMP_IF_FALSE,
    }
)
_STRING_OPERAND_OPCODES = frozenset({Opcode.LOAD_GLOBAL, Opcode.STORE_GLOBAL})


def expected_operand_kind(opcode: Opcode) -> str:
    """Return the required operand kind: integer, string, or none."""
    if opcode in _INTEGER_OPERAND_OPCODES:
        return "integer"
    if opcode in _STRING_OPERAND_OPCODES:
        return "string"
    return "none"


def stack_requirement(opcode: Opcode) -> int:
    """Return the minimum stack depth required before executing an opcode."""
    if opcode in {
        Opcode.POP,
        Opcode.STORE_LOCAL,
        Opcode.STORE_GLOBAL,
        Opcode.PRINT,
        Opcode.JUMP_IF_FALSE,
        Opcode.NEGATE,
        Opcode.NOT,
    }:
        return 1
    if opcode in {
        Opcode.ADD,
        Opcode.SUBTRACT,
        Opcode.MULTIPLY,
        Opcode.DIVIDE,
        Opcode.MODULO,
        Opcode.EQUAL,
        Opcode.NOT_EQUAL,
        Opcode.LESS,
        Opcode.LESS_EQUAL,
        Opcode.GREATER,
        Opcode.GREATER_EQUAL,
        Opcode.AND,
        Opcode.OR,
    }:
        return 2
    if opcode is Opcode.DUP:
        return 1
    return 0


def stack_delta(opcode: Opcode) -> int:
    """Return the net stack-height change caused by an opcode."""
    if opcode in {
        Opcode.CONSTANT,
        Opcode.LOAD_LOCAL,
        Opcode.LOAD_GLOBAL,
    }:
        return 1
    if opcode in {
        Opcode.POP,
        Opcode.STORE_LOCAL,
        Opcode.STORE_GLOBAL,
        Opcode.PRINT,
        Opcode.JUMP_IF_FALSE,
    }:
        return -1
    if opcode in {
        Opcode.ADD,
        Opcode.SUBTRACT,
        Opcode.MULTIPLY,
        Opcode.DIVIDE,
        Opcode.MODULO,
        Opcode.EQUAL,
        Opcode.NOT_EQUAL,
        Opcode.LESS,
        Opcode.LESS_EQUAL,
        Opcode.GREATER,
        Opcode.GREATER_EQUAL,
        Opcode.AND,
        Opcode.OR,
    }:
        return -1
    if opcode is Opcode.DUP:
        return 1
    return 0
