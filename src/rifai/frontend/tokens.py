"""Token definitions for the Rifa'i language."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

LiteralValue = int | float | str | bool | None


class TokenType(str, Enum):
    """All lexical token types recognized by the Rifa'i Lexer."""

    # Structural
    EOF = "EOF"

    # Identifiers and literals
    IDENTIFIER = "IDENTIFIER"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"

    # Keywords — declarations and control flow
    FN = "FN"
    LET = "LET"
    RETURN = "RETURN"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    PRINT = "PRINT"
    IMPORT = "IMPORT"
    STRUCT = "STRUCT"
    ENUM = "ENUM"

    # Keywords — boolean literals
    TRUE = "TRUE"
    FALSE = "FALSE"

    # Keywords — static type specifiers
    TYPE_INT = "TYPE_INT"
    TYPE_FLOAT = "TYPE_FLOAT"
    TYPE_BOOL = "TYPE_BOOL"
    TYPE_STRING = "TYPE_STRING"
    TYPE_VOID = "TYPE_VOID"

    # Keywords — logical operators
    AND = "AND"
    OR = "OR"
    NOT = "NOT"

    # Operators
    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"
    MODULO = "MODULO"
    ASSIGN = "ASSIGN"
    EQUAL_EQUAL = "EQUAL_EQUAL"
    BANG_EQUAL = "BANG_EQUAL"
    LESS = "LESS"
    LESS_EQUAL = "LESS_EQUAL"
    GREATER = "GREATER"
    GREATER_EQUAL = "GREATER_EQUAL"

    # Delimiters
    LEFT_PAREN = "LEFT_PAREN"
    RIGHT_PAREN = "RIGHT_PAREN"
    LEFT_BRACE = "LEFT_BRACE"
    RIGHT_BRACE = "RIGHT_BRACE"
    LEFT_BRACKET = "LEFT_BRACKET"
    RIGHT_BRACKET = "RIGHT_BRACKET"
    COLON = "COLON"
    SEMICOLON = "SEMICOLON"
    COMMA = "COMMA"
    DOT = "DOT"
    ARROW = "ARROW"


KEYWORDS: Final[dict[str, TokenType]] = {
    "fn": TokenType.FN,
    "let": TokenType.LET,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "print": TokenType.PRINT,
    "import": TokenType.IMPORT,
    "struct": TokenType.STRUCT,
    "enum": TokenType.ENUM,
    "int": TokenType.TYPE_INT,
    "float": TokenType.TYPE_FLOAT,
    "bool": TokenType.TYPE_BOOL,
    "string": TokenType.TYPE_STRING,
    "void": TokenType.TYPE_VOID,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
}


@dataclass(frozen=True, slots=True)
class Token:
    """Immutable lexical token with exact source coordinates."""

    token_type: TokenType
    lexeme: str
    literal: LiteralValue
    line: int
    column: int
    start_offset: int
    end_offset: int

    def __str__(self) -> str:
        base = f"{self.line}:{self.column} {self.token_type.name} {self.lexeme!r}"
        if self.literal is not None:
            return f"{base} literal={self.literal!r}"
        return base
