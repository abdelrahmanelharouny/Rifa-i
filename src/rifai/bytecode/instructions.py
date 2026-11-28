"""Instruction definitions for the Rifa'i stack-based bytecode."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Opcode(str, Enum):
    """Version 4 bytecode instructions supported by the Rifa'i VM."""

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
    CALL = "CALL"
    RETURN = "RETURN"

    ARRAY_NEW_INT = "ARRAY_NEW_INT"
    ARRAY_NEW_FLOAT = "ARRAY_NEW_FLOAT"
    ARRAY_NEW_BOOL = "ARRAY_NEW_BOOL"
    ARRAY_NEW_STRING = "ARRAY_NEW_STRING"
    ARRAY_GET = "ARRAY_GET"
    ARRAY_SET = "ARRAY_SET"
    LENGTH = "LENGTH"
    ARRAY_PUSH = "ARRAY_PUSH"
    ARRAY_POP = "ARRAY_POP"

    # Nominal records and unit enums (bytecode v5).
    STRUCT_NEW = "STRUCT_NEW"
    FIELD_GET = "FIELD_GET"
    FIELD_SET = "FIELD_SET"
    ENUM_NEW = "ENUM_NEW"

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


_INTEGER_OPERAND_OPCODES = frozenset(
    {
        Opcode.CONSTANT,
        Opcode.LOAD_LOCAL,
        Opcode.STORE_LOCAL,
        Opcode.JUMP,
        Opcode.JUMP_IF_FALSE,
        Opcode.ARRAY_NEW_INT,
        Opcode.ARRAY_NEW_FLOAT,
        Opcode.ARRAY_NEW_BOOL,
        Opcode.ARRAY_NEW_STRING,
    }
)
_STRING_OPERAND_OPCODES = frozenset(
    {Opcode.LOAD_GLOBAL, Opcode.STORE_GLOBAL, Opcode.CALL, Opcode.STRUCT_NEW, Opcode.FIELD_GET, Opcode.FIELD_SET, Opcode.ENUM_NEW}
)


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
        Opcode.POP, Opcode.STORE_LOCAL, Opcode.STORE_GLOBAL, Opcode.PRINT,
        Opcode.JUMP_IF_FALSE, Opcode.NEGATE, Opcode.NOT, Opcode.FIELD_GET,
    }:
        return 1
    if opcode in {
        Opcode.ADD, Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE,
        Opcode.MODULO, Opcode.EQUAL, Opcode.NOT_EQUAL, Opcode.LESS,
        Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL,
        Opcode.AND, Opcode.OR, Opcode.ARRAY_PUSH, Opcode.FIELD_SET,
    }:
        return 2
    if opcode is Opcode.ARRAY_SET:
        return 3
    if opcode in (Opcode.ARRAY_GET,):
        return 2
    if opcode in (Opcode.LENGTH, Opcode.ARRAY_POP, Opcode.DUP):
        return 1
    return 0


def stack_delta(opcode: Opcode) -> int:
    """Return the net stack-height change caused by a non-call opcode."""
    if opcode in {
        Opcode.CONSTANT, Opcode.LOAD_LOCAL, Opcode.LOAD_GLOBAL,
        Opcode.STRUCT_NEW, Opcode.ENUM_NEW,
    }:
        return 1
    if opcode in {
        Opcode.POP, Opcode.STORE_LOCAL, Opcode.STORE_GLOBAL,
        Opcode.PRINT, Opcode.JUMP_IF_FALSE,
    }:
        return -1
    if opcode in {
        Opcode.ADD, Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE,
        Opcode.MODULO, Opcode.EQUAL, Opcode.NOT_EQUAL, Opcode.LESS,
        Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL,
        Opcode.AND, Opcode.OR, Opcode.ARRAY_GET,
    }:
        return -1
    if opcode in (Opcode.LENGTH, Opcode.ARRAY_POP, Opcode.FIELD_GET):
        return 0
    if opcode is Opcode.ARRAY_SET:
        return -3
    if opcode in (Opcode.ARRAY_PUSH, Opcode.FIELD_SET):
        return -2
    if opcode is Opcode.DUP:
        return 1
    return 0
