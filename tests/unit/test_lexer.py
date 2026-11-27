"""Comprehensive unit tests for the Rifa'i Lexer."""

from __future__ import annotations

import pytest

from rifai.errors.diagnostics import DiagnosticPhase
from rifai.frontend.lexer import Lexer
from rifai.frontend.tokens import KEYWORDS, Token, TokenType


def _assert_offsets_match_source(source: str, tokens: tuple[Token, ...]) -> None:
    for token in tokens:
        assert source[token.start_offset : token.end_offset] == token.lexeme


def test_empty_source_produces_only_eof() -> None:
    result = Lexer("").scan_tokens()

    assert not result.has_errors
    assert len(result.tokens) == 1
    eof = result.tokens[0]
    assert eof.token_type is TokenType.EOF
    assert eof.lexeme == ""
    assert eof.literal is None
    assert (eof.line, eof.column) == (1, 1)
    assert (eof.start_offset, eof.end_offset) == (0, 0)


def test_all_keywords_recognized_with_distinct_tokens() -> None:
    source = " ".join(KEYWORDS.keys())
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    expected_types = [*KEYWORDS.values(), TokenType.EOF]
    assert [t.token_type for t in result.tokens] == expected_types
    _assert_offsets_match_source(source, result.tokens)

    bool_tokens = {t.lexeme: t.literal for t in result.tokens if t.lexeme in ("true", "false")}
    assert bool_tokens == {"true": True, "false": False}


def test_identifiers_and_keyword_prefixes() -> None:
    source = "foo _bar _123 fn_name integer let1 whileLoop _ "
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    non_eof = result.tokens[:-1]
    assert [t.token_type for t in non_eof] == [TokenType.IDENTIFIER] * 8
    assert [t.lexeme for t in non_eof] == [
        "foo",
        "_bar",
        "_123",
        "fn_name",
        "integer",
        "let1",
        "whileLoop",
        "_",
    ]
    assert all(t.literal is None for t in non_eof)
    _assert_offsets_match_source(source, result.tokens)


def test_integer_literals() -> None:
    source = "0 7 42 1024"
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    non_eof = result.tokens[:-1]
    assert [t.token_type for t in non_eof] == [TokenType.INTEGER] * 4
    assert [t.literal for t in non_eof] == [0, 7, 42, 1024]
    assert [t.lexeme for t in non_eof] == ["0", "7", "42", "1024"]
    _assert_offsets_match_source(source, result.tokens)


def test_float_literals() -> None:
    source = "0.0 19.5 3.14159"
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    non_eof = result.tokens[:-1]
    assert [t.token_type for t in non_eof] == [TokenType.FLOAT] * 3
    assert [t.literal for t in non_eof] == [0.0, 19.5, 3.14159]
    assert [t.lexeme for t in non_eof] == ["0.0", "19.5", "3.14159"]
    _assert_offsets_match_source(source, result.tokens)


def test_string_literals_and_escape_sequences() -> None:
    source = '"" "Rifa\'i" "a\\nb\\tc\\rd\\"e\\\\f"'
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    non_eof = result.tokens[:-1]
    assert [t.token_type for t in non_eof] == [TokenType.STRING] * 3
    assert [t.literal for t in non_eof] == [
        "",
        "Rifa'i",
        'a\nb\tc\rd"e\\f',
    ]
    _assert_offsets_match_source(source, result.tokens)


def test_operators_and_delimiters() -> None:
    source = "+ - * / % = == != < <= > >= ( ) { } : ; , ->"
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    assert [t.token_type for t in result.tokens] == [
        TokenType.PLUS,
        TokenType.MINUS,
        TokenType.STAR,
        TokenType.SLASH,
        TokenType.MODULO,
        TokenType.ASSIGN,
        TokenType.EQUAL_EQUAL,
        TokenType.BANG_EQUAL,
        TokenType.LESS,
        TokenType.LESS_EQUAL,
        TokenType.GREATER,
        TokenType.GREATER_EQUAL,
        TokenType.LEFT_PAREN,
        TokenType.RIGHT_PAREN,
        TokenType.LEFT_BRACE,
        TokenType.RIGHT_BRACE,
        TokenType.COLON,
        TokenType.SEMICOLON,
        TokenType.COMMA,
        TokenType.ARROW,
        TokenType.EOF,
    ]
    _assert_offsets_match_source(source, result.tokens)


def test_adjacent_operator_disambiguation() -> None:
    source = "x=-1;a!=b;c==d;e<=f;g>=h;fn f()->int{return a/b;}"
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    assert [t.token_type for t in result.tokens[:-1]] == [
        TokenType.IDENTIFIER,
        TokenType.ASSIGN,
        TokenType.MINUS,
        TokenType.INTEGER,
        TokenType.SEMICOLON,
        TokenType.IDENTIFIER,
        TokenType.BANG_EQUAL,
        TokenType.IDENTIFIER,
        TokenType.SEMICOLON,
        TokenType.IDENTIFIER,
        TokenType.EQUAL_EQUAL,
        TokenType.IDENTIFIER,
        TokenType.SEMICOLON,
        TokenType.IDENTIFIER,
        TokenType.LESS_EQUAL,
        TokenType.IDENTIFIER,
        TokenType.SEMICOLON,
        TokenType.IDENTIFIER,
        TokenType.GREATER_EQUAL,
        TokenType.IDENTIFIER,
        TokenType.SEMICOLON,
        TokenType.FN,
        TokenType.IDENTIFIER,
        TokenType.LEFT_PAREN,
        TokenType.RIGHT_PAREN,
        TokenType.ARROW,
        TokenType.TYPE_INT,
        TokenType.LEFT_BRACE,
        TokenType.RETURN,
        TokenType.IDENTIFIER,
        TokenType.SLASH,
        TokenType.IDENTIFIER,
        TokenType.SEMICOLON,
        TokenType.RIGHT_BRACE,
    ]
    _assert_offsets_match_source(source, result.tokens)


def test_logical_keywords() -> None:
    source = "not a and b or false"
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    assert [t.token_type for t in result.tokens] == [
        TokenType.NOT,
        TokenType.IDENTIFIER,
        TokenType.AND,
        TokenType.IDENTIFIER,
        TokenType.OR,
        TokenType.FALSE,
        TokenType.EOF,
    ]


def test_single_line_comments_and_whitespace() -> None:
    source = "  \t let x: int = 1; // comment with symbols @!$ \n // full line comment\n\treturn x;"
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    assert [(t.token_type, t.line, t.column) for t in result.tokens] == [
        (TokenType.LET, 1, 5),
        (TokenType.IDENTIFIER, 1, 9),
        (TokenType.COLON, 1, 10),
        (TokenType.TYPE_INT, 1, 12),
        (TokenType.ASSIGN, 1, 16),
        (TokenType.INTEGER, 1, 18),
        (TokenType.SEMICOLON, 1, 19),
        (TokenType.RETURN, 3, 2),
        (TokenType.IDENTIFIER, 3, 9),
        (TokenType.SEMICOLON, 3, 10),
        (TokenType.EOF, 3, 11),
    ]
    _assert_offsets_match_source(source, result.tokens)


def test_lf_and_crlf_line_endings_produce_accurate_locations() -> None:
    lf_source = "let a: int = 1;\nlet b: int = 2;\n"
    crlf_source = "let a: int = 1;\r\nlet b: int = 2;\r\n"

    lf_result = Lexer(lf_source).scan_tokens()
    crlf_result = Lexer(crlf_source).scan_tokens()

    assert not lf_result.has_errors
    assert not crlf_result.has_errors

    assert [(t.token_type, t.lexeme, t.line, t.column) for t in lf_result.tokens] == [
        (t.token_type, t.lexeme, t.line, t.column) for t in crlf_result.tokens
    ]
    _assert_offsets_match_source(lf_source, lf_result.tokens)
    _assert_offsets_match_source(crlf_source, crlf_result.tokens)
    assert crlf_result.tokens[-1].line == 3
    assert crlf_result.tokens[-1].column == 1


@pytest.mark.parametrize(
    ("source", "expected_line", "expected_column"),
    [
        ("@", 1, 1),
        ("let x: int = !true;", 1, 14),
        ("let x: int = 1;\n$", 2, 1),
        ("let x: int = 1;\r\n  ?", 2, 3),
    ],
)
def test_invalid_characters_report_diagnostics(
    source: str, expected_line: int, expected_column: int
) -> None:
    result = Lexer(source).scan_tokens()

    assert result.has_errors
    assert len(result.diagnostics) == 1
    diag = result.diagnostics[0]
    assert diag.phase is DiagnosticPhase.LEXER
    assert diag.line == expected_line
    assert diag.column == expected_column
    assert result.tokens[-1].token_type is TokenType.EOF


def test_unterminated_string_at_eof_and_newline() -> None:
    eof_source = 'let s: string = "hello'
    eof_result = Lexer(eof_source).scan_tokens()
    assert len(eof_result.diagnostics) == 1
    assert eof_result.diagnostics[0].line == 1
    assert eof_result.diagnostics[0].column == 17
    assert eof_result.tokens[-1].token_type is TokenType.EOF

    newline_source = 'let s: string = "hello\nlet y: int = 5;'
    newline_result = Lexer(newline_source).scan_tokens()
    assert len(newline_result.diagnostics) == 1
    assert newline_result.diagnostics[0].line == 1
    assert newline_result.diagnostics[0].column == 17
    assert [t.lexeme for t in newline_result.tokens if t.line == 2] == [
        "let",
        "y",
        ":",
        "int",
        "=",
        "5",
        ";",
        "",
    ]


def test_unterminated_string_ending_with_trailing_backslash() -> None:
    result = Lexer('"abc\\').scan_tokens()

    assert len(result.diagnostics) == 1
    assert "Unterminated string" in result.diagnostics[0].message
    assert result.tokens[-1].token_type is TokenType.EOF


def test_invalid_escape_sequence_reported_and_recovers() -> None:
    source = r'let s: string = "hi\q!"; let n: int = 7;'
    result = Lexer(source).scan_tokens()

    assert len(result.diagnostics) == 1
    diag = result.diagnostics[0]
    assert diag.phase is DiagnosticPhase.LEXER
    assert diag.line == 1
    assert diag.column == 20
    assert r"\q" in diag.message
    assert [t.lexeme for t in result.tokens] == [
        "let",
        "s",
        ":",
        "string",
        "=",
        ";",
        "let",
        "n",
        ":",
        "int",
        "=",
        "7",
        ";",
        "",
    ]


@pytest.mark.parametrize(
    "bad_literal",
    [
        "12.",
        ".5",
        "1.2.3",
        "123abc",
        "0x10",
    ],
)
def test_malformed_numeric_literals(bad_literal: str) -> None:
    source = f"let v: float = {bad_literal};"
    result = Lexer(source).scan_tokens()

    assert len(result.diagnostics) == 1
    diag = result.diagnostics[0]
    assert diag.phase is DiagnosticPhase.LEXER
    assert diag.line == 1
    assert diag.column == 16
    assert bad_literal in diag.message
    assert result.tokens[-2].token_type is TokenType.SEMICOLON
    assert result.tokens[-1].token_type is TokenType.EOF


def test_multiple_lexical_errors_accumulated_in_single_pass() -> None:
    source = (
        "let a: int = @;\n"
        'let b: string = "unterminated\n'
        "let c: float = 12.;\r\n"
        'let d: string = "bad\\z";\n'
        "let ok: bool = !false;\n"
    )
    result = Lexer(source).scan_tokens()

    assert result.has_errors
    assert len(result.diagnostics) == 5
    assert [(d.line, d.column) for d in result.diagnostics] == [
        (1, 14),
        (2, 17),
        (3, 16),
        (4, 21),
        (5, 16),
    ]
    assert result.tokens[-1].token_type is TokenType.EOF


def test_realistic_rifai_program() -> None:
    source = (
        "// Factorial example\n"
        "fn fact(n: int) -> int {\n"
        "    if (n <= 1) {\n"
        "        return 1;\n"
        "    } else {\n"
        "        return n * fact(n - 1);\n"
        "    }\n"
        "}\n"
        "print(fact(5));\n"
    )
    result = Lexer(source).scan_tokens()

    assert not result.has_errors
    _assert_offsets_match_source(source, result.tokens)
    assert [t.token_type for t in result.tokens] == [
        TokenType.FN,
        TokenType.IDENTIFIER,
        TokenType.LEFT_PAREN,
        TokenType.IDENTIFIER,
        TokenType.COLON,
        TokenType.TYPE_INT,
        TokenType.RIGHT_PAREN,
        TokenType.ARROW,
        TokenType.TYPE_INT,
        TokenType.LEFT_BRACE,
        TokenType.IF,
        TokenType.LEFT_PAREN,
        TokenType.IDENTIFIER,
        TokenType.LESS_EQUAL,
        TokenType.INTEGER,
        TokenType.RIGHT_PAREN,
        TokenType.LEFT_BRACE,
        TokenType.RETURN,
        TokenType.INTEGER,
        TokenType.SEMICOLON,
        TokenType.RIGHT_BRACE,
        TokenType.ELSE,
        TokenType.LEFT_BRACE,
        TokenType.RETURN,
        TokenType.IDENTIFIER,
        TokenType.STAR,
        TokenType.IDENTIFIER,
        TokenType.LEFT_PAREN,
        TokenType.IDENTIFIER,
        TokenType.MINUS,
        TokenType.INTEGER,
        TokenType.RIGHT_PAREN,
        TokenType.SEMICOLON,
        TokenType.RIGHT_BRACE,
        TokenType.RIGHT_BRACE,
        TokenType.PRINT,
        TokenType.LEFT_PAREN,
        TokenType.IDENTIFIER,
        TokenType.LEFT_PAREN,
        TokenType.INTEGER,
        TokenType.RIGHT_PAREN,
        TokenType.RIGHT_PAREN,
        TokenType.SEMICOLON,
        TokenType.EOF,
    ]
