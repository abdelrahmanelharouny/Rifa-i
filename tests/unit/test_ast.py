"""Unit tests for Rifa'i AST nodes, SourceSpan, and AST formatting."""

from __future__ import annotations

from rifai.frontend.ast_nodes import (
    BinaryExpression,
    LiteralExpression,
    Program,
    SourceSpan,
    TypeAnnotation,
    VariableDeclaration,
    format_ast,
)
from rifai.frontend.tokens import Token, TokenType


def _tok(token_type: TokenType, lexeme: str, literal: object, col: int) -> Token:
    return Token(
        token_type=token_type,
        lexeme=lexeme,
        literal=literal,  # type: ignore[arg-type]
        line=1,
        column=col,
        start_offset=col - 1,
        end_offset=col - 1 + len(lexeme),
    )


def test_source_span_from_token_and_between() -> None:
    start = _tok(TokenType.LET, "let", None, 1)
    end = _tok(TokenType.SEMICOLON, ";", None, 20)

    single = SourceSpan.from_token(start)
    combined = SourceSpan.between(start, end)

    assert (single.line, single.column, single.start_offset, single.end_offset) == (
        1,
        1,
        0,
        3,
    )
    assert (combined.line, combined.column, combined.start_offset, combined.end_offset) == (
        1,
        1,
        0,
        20,
    )


def test_ast_node_construction_and_format_ast_preserves_precedence() -> None:
    let_tok = _tok(TokenType.LET, "let", None, 1)
    name_tok = _tok(TokenType.IDENTIFIER, "result", None, 5)
    type_tok = _tok(TokenType.TYPE_INT, "int", None, 13)
    lit10_tok = _tok(TokenType.INTEGER, "10", 10, 19)
    plus_tok = _tok(TokenType.PLUS, "+", None, 22)
    lit20_tok = _tok(TokenType.INTEGER, "20", 20, 24)
    star_tok = _tok(TokenType.STAR, "*", None, 27)
    lit2_tok = _tok(TokenType.INTEGER, "2", 2, 29)
    semi_tok = _tok(TokenType.SEMICOLON, ";", None, 30)

    mul_expr = BinaryExpression(
        left=LiteralExpression(20, lit20_tok, SourceSpan.from_token(lit20_tok)),
        operator=star_tok,
        right=LiteralExpression(2, lit2_tok, SourceSpan.from_token(lit2_tok)),
        span=SourceSpan.between(lit20_tok, lit2_tok),
    )
    add_expr = BinaryExpression(
        left=LiteralExpression(10, lit10_tok, SourceSpan.from_token(lit10_tok)),
        operator=plus_tok,
        right=mul_expr,
        span=SourceSpan.between(lit10_tok, lit2_tok),
    )
    decl = VariableDeclaration(
        name="result",
        name_token=name_tok,
        type_annotation=TypeAnnotation("int", type_tok, SourceSpan.from_token(type_tok)),
        initializer=add_expr,
        span=SourceSpan.between(let_tok, semi_tok),
    )
    program = Program(declarations=(decl,), span=decl.span)

    rendered = format_ast(program)
    assert "Program" in rendered
    assert "VariableDeclaration result: int" in rendered
    assert "BinaryExpression(+)" in rendered
    assert "BinaryExpression(*)" in rendered
    assert "Literal(10)" in rendered
    assert "Literal(20)" in rendered
    assert "Literal(2)" in rendered
