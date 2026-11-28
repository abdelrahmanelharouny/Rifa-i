"""Unit tests for Rifa'i Token and TokenType definitions."""

from __future__ import annotations

import dataclasses
import pytest

from rifai.frontend.tokens import KEYWORDS, Token, TokenType


def test_token_construction_and_fields() -> None:
    token = Token(
        token_type=TokenType.INTEGER,
        lexeme="42",
        literal=42,
        line=3,
        column=12,
        start_offset=25,
        end_offset=27,
    )

    assert token.token_type is TokenType.INTEGER
    assert token.lexeme == "42"
    assert token.literal == 42
    assert token.line == 3
    assert token.column == 12
    assert token.start_offset == 25
    assert token.end_offset == 27


def test_token_is_immutable() -> None:
    token = Token(
        token_type=TokenType.IDENTIFIER,
        lexeme="count",
        literal=None,
        line=1,
        column=5,
        start_offset=4,
        end_offset=9,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        token.lexeme = "other"  # type: ignore[misc]


def test_token_string_and_repr_representations() -> None:
    int_token = Token(TokenType.INTEGER, "10", 10, 1, 1, 0, 2)
    kw_token = Token(TokenType.FN, "fn", None, 2, 3, 5, 7)

    assert str(int_token) == "1:1 INTEGER '10' literal=10"
    assert str(kw_token) == "2:3 FN 'fn'"
    assert "TokenType.INTEGER" in repr(int_token)
    assert "lexeme='fn'" in repr(kw_token)


def test_all_reserved_keywords_have_distinct_token_types() -> None:
    expected_keywords = {
        "fn": TokenType.FN,
        "let": TokenType.LET,
        "return": TokenType.RETURN,
        "if": TokenType.IF,
        "else": TokenType.ELSE,
        "while": TokenType.WHILE,
        "for": TokenType.FOR,
        "break": TokenType.BREAK,
        "continue": TokenType.CONTINUE,
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

    assert KEYWORDS == expected_keywords
    assert len(set(KEYWORDS.values())) == len(expected_keywords)


def test_required_token_types_exist() -> None:
    required_names = {
        "EOF",
        "IDENTIFIER",
        "INTEGER",
        "FLOAT",
        "STRING",
        "FN",
        "LET",
        "RETURN",
        "IF",
        "ELSE",
        "WHILE",
        "FOR",
        "BREAK",
        "CONTINUE",
        "TRUE",
        "FALSE",
        "PRINT",
        "IMPORT",
        "STRUCT",
        "ENUM",
        "TYPE_INT",
        "TYPE_FLOAT",
        "TYPE_BOOL",
        "TYPE_STRING",
        "TYPE_VOID",
        "AND",
        "OR",
        "NOT",
        "PLUS",
        "MINUS",
        "STAR",
        "SLASH",
        "MODULO",
        "ASSIGN",
        "EQUAL_EQUAL",
        "BANG_EQUAL",
        "LESS",
        "LESS_EQUAL",
        "GREATER",
        "GREATER_EQUAL",
        "LEFT_PAREN",
        "RIGHT_PAREN",
        "LEFT_BRACE",
        "RIGHT_BRACE",
        "COLON",
        "SEMICOLON",
        "COMMA",
        "DOT",
        "ARROW",
    }

    actual_names = {member.name for member in TokenType}
    assert required_names.issubset(actual_names)
