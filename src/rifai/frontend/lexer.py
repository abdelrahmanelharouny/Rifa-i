"""Lexical analyzer for the Rifa'i programming language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.tokens import KEYWORDS, LiteralValue, Token, TokenType

_SINGLE_CHAR_TOKENS: Final[dict[str, TokenType]] = {
    "+": TokenType.PLUS,
    "*": TokenType.STAR,
    "%": TokenType.MODULO,
    "(": TokenType.LEFT_PAREN,
    ")": TokenType.RIGHT_PAREN,
    "{": TokenType.LEFT_BRACE,
    "}": TokenType.RIGHT_BRACE,
    "[": TokenType.LEFT_BRACKET,
    "]": TokenType.RIGHT_BRACKET,
    ":": TokenType.COLON,
    ";": TokenType.SEMICOLON,
    ",": TokenType.COMMA,
}

_TWO_CHAR_OPERATORS: Final[dict[str, tuple[str, TokenType, TokenType]]] = {
    "-": (">", TokenType.ARROW, TokenType.MINUS),
    "=": ("=", TokenType.EQUAL_EQUAL, TokenType.ASSIGN),
    "<": ("=", TokenType.LESS_EQUAL, TokenType.LESS),
    ">": ("=", TokenType.GREATER_EQUAL, TokenType.GREATER),
}

_STRING_ESCAPES: Final[dict[str, str]] = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
}


def _is_ascii_letter(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _is_ascii_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return _is_ascii_letter(ch) or ch == "_"


def _is_ident_continue(ch: str) -> bool:
    return _is_ident_start(ch) or _is_ascii_digit(ch)


@dataclass(frozen=True, slots=True)
class LexResult:
    """Output produced by the Rifa'i Lexer."""

    tokens: tuple[Token, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def has_errors(self) -> bool:
        """Return True when one or more lexical errors were recorded."""
        return len(self.diagnostics) > 0


class Lexer:
    """Sequential character scanner converting Rifa'i source text into tokens."""

    def __init__(self, source: str) -> None:
        self._source = source
        self._length = len(source)
        self._index = 0
        self._line = 1
        self._column = 1
        self._tokens: list[Token] = []
        self._diagnostics: list[Diagnostic] = []

    def scan_tokens(self) -> LexResult:
        """Scan the entire source string and return tokens plus accumulated diagnostics."""
        self._index = 0
        self._line = 1
        self._column = 1
        self._tokens = []
        self._diagnostics = []

        while not self._is_at_end():
            self._scan_next()

        self._tokens.append(
            Token(
                token_type=TokenType.EOF,
                lexeme="",
                literal=None,
                line=self._line,
                column=self._column,
                start_offset=self._index,
                end_offset=self._index,
            )
        )
        return LexResult(
            tokens=tuple(self._tokens),
            diagnostics=tuple(self._diagnostics),
        )

    def _is_at_end(self) -> bool:
        return self._index >= self._length

    def _peek(self, lookahead: int = 0) -> str:
        pos = self._index + lookahead
        if pos >= self._length:
            return ""
        return self._source[pos]

    def _advance(self) -> str:
        ch = self._source[self._index]
        self._index += 1
        if ch == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return ch

    def _match(self, expected: str) -> bool:
        if self._peek() != expected:
            return False
        self._advance()
        return True

    def _emit_token(
        self,
        token_type: TokenType,
        start_offset: int,
        start_line: int,
        start_column: int,
        literal: LiteralValue = None,
    ) -> None:
        lexeme = self._source[start_offset : self._index]
        self._tokens.append(
            Token(
                token_type=token_type,
                lexeme=lexeme,
                literal=literal,
                line=start_line,
                column=start_column,
                start_offset=start_offset,
                end_offset=self._index,
            )
        )

    def _emit_error(
        self,
        message: str,
        line: int,
        column: int,
        start_offset: int,
        end_offset: int | None = None,
    ) -> None:
        self._diagnostics.append(
            Diagnostic(
                phase=DiagnosticPhase.LEXER,
                message=message,
                line=line,
                column=column,
                start_offset=start_offset,
                end_offset=self._index if end_offset is None else end_offset,
            )
        )

    def _scan_next(self) -> None:
        start_offset = self._index
        start_line = self._line
        start_column = self._column
        ch = self._advance()

        if ch in (" ", "\t", "\n"):
            return

        if ch == "\r":
            if self._match("\n"):
                return
            self._emit_error(
                "Unexpected bare carriage return '\\r' (expected CRLF or LF line ending).",
                start_line,
                start_column,
                start_offset,
            )
            return

        single_type = _SINGLE_CHAR_TOKENS.get(ch)
        if single_type is not None:
            self._emit_token(single_type, start_offset, start_line, start_column)
            return

        two_char = _TWO_CHAR_OPERATORS.get(ch)
        if two_char is not None:
            expected_second, paired_type, fallback_type = two_char
            token_type = paired_type if self._match(expected_second) else fallback_type
            self._emit_token(token_type, start_offset, start_line, start_column)
            return

        if ch == "!":
            if self._match("="):
                self._emit_token(
                    TokenType.BANG_EQUAL, start_offset, start_line, start_column
                )
            else:
                self._emit_error(
                    "Unexpected character '!' (use 'not' for logical negation or '!=' for inequality).",
                    start_line,
                    start_column,
                    start_offset,
                )
            return

        if ch == "/":
            if self._match("/"):
                self._skip_comment()
            else:
                self._emit_token(TokenType.SLASH, start_offset, start_line, start_column)
            return

        if ch == '"':
            self._scan_string(start_offset, start_line, start_column)
            return

        if _is_ascii_digit(ch):
            self._scan_number(start_offset, start_line, start_column)
            return

        if ch == "." and _is_ascii_digit(self._peek()):
            self._consume_invalid_numeric_tail()
            lexeme = self._source[start_offset : self._index]
            self._emit_error(
                f"Malformed floating-point literal '{lexeme}': digits are required before the decimal point.",
                start_line,
                start_column,
                start_offset,
            )
            return

        if _is_ident_start(ch):
            self._scan_identifier_or_keyword(start_offset, start_line, start_column)
            return

        self._emit_error(
            f"Unexpected character {ch!r}.",
            start_line,
            start_column,
            start_offset,
        )

    def _skip_comment(self) -> None:
        while not self._is_at_end() and self._peek() not in ("\n", "\r"):
            self._advance()

    def _scan_string(
        self, start_offset: int, start_line: int, start_column: int
    ) -> None:
        chars: list[str] = []
        has_escape_error = False

        while not self._is_at_end():
            ch = self._peek()

            if ch == '"':
                self._advance()
                if not has_escape_error:
                    self._emit_token(
                        TokenType.STRING,
                        start_offset,
                        start_line,
                        start_column,
                        literal="".join(chars),
                    )
                return

            if ch in ("\n", "\r"):
                self._emit_error(
                    "Unterminated string literal.",
                    start_line,
                    start_column,
                    start_offset,
                )
                return

            if ch == "\\":
                esc_offset = self._index
                esc_line = self._line
                esc_column = self._column
                self._advance()

                if self._is_at_end() or self._peek() in ("\n", "\r"):
                    self._emit_error(
                        "Unterminated string literal.",
                        start_line,
                        start_column,
                        start_offset,
                    )
                    return

                esc_char = self._advance()
                mapped = _STRING_ESCAPES.get(esc_char)
                if mapped is not None:
                    chars.append(mapped)
                else:
                    has_escape_error = True
                    self._emit_error(
                        f"Invalid escape sequence '\\{esc_char}'.",
                        esc_line,
                        esc_column,
                        esc_offset,
                    )
                continue

            chars.append(self._advance())

        self._emit_error(
            "Unterminated string literal.",
            start_line,
            start_column,
            start_offset,
        )

    def _scan_number(
        self, start_offset: int, start_line: int, start_column: int
    ) -> None:
        while _is_ascii_digit(self._peek()):
            self._advance()

        if self._peek() == ".":
            self._advance()
            if not _is_ascii_digit(self._peek()):
                self._consume_invalid_numeric_tail()
                lexeme = self._source[start_offset : self._index]
                self._emit_error(
                    f"Malformed floating-point literal '{lexeme}': digits are required after the decimal point.",
                    start_line,
                    start_column,
                    start_offset,
                )
                return

            while _is_ascii_digit(self._peek()):
                self._advance()

            if self._peek() == "." or _is_ident_continue(self._peek()):
                self._consume_invalid_numeric_tail()
                lexeme = self._source[start_offset : self._index]
                self._emit_error(
                    f"Malformed numeric literal '{lexeme}'.",
                    start_line,
                    start_column,
                    start_offset,
                )
                return

            lexeme = self._source[start_offset : self._index]
            self._emit_token(
                TokenType.FLOAT,
                start_offset,
                start_line,
                start_column,
                literal=float(lexeme),
            )
            return

        if _is_ident_start(self._peek()):
            self._consume_invalid_numeric_tail()
            lexeme = self._source[start_offset : self._index]
            self._emit_error(
                f"Malformed numeric literal '{lexeme}'.",
                start_line,
                start_column,
                start_offset,
            )
            return

        lexeme = self._source[start_offset : self._index]
        self._emit_token(
            TokenType.INTEGER,
            start_offset,
            start_line,
            start_column,
            literal=int(lexeme),
        )

    def _consume_invalid_numeric_tail(self) -> None:
        while not self._is_at_end() and (
            self._peek() == "." or _is_ident_continue(self._peek())
        ):
            self._advance()

    def _scan_identifier_or_keyword(
        self, start_offset: int, start_line: int, start_column: int
    ) -> None:
        while _is_ident_continue(self._peek()):
            self._advance()

        lexeme = self._source[start_offset : self._index]
        token_type = KEYWORDS.get(lexeme, TokenType.IDENTIFIER)
        literal: LiteralValue = None
        if token_type is TokenType.TRUE:
            literal = True
        elif token_type is TokenType.FALSE:
            literal = False

        self._emit_token(
            token_type,
            start_offset,
            start_line,
            start_column,
            literal=literal,
        )
