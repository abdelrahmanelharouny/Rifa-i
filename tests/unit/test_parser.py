"""Comprehensive unit tests for the Rifa'i Recursive Descent Parser."""

from __future__ import annotations

from rifai.errors.diagnostics import DiagnosticPhase
from rifai.frontend.ast_nodes import (
    AssignmentStatement,
    BinaryExpression,
    BlockStatement,
    ExpressionStatement,
    FunctionCallExpression,
    FunctionDeclaration,
    GroupingExpression,
    IfStatement,
    LiteralExpression,
    PrintStatement,
    ReturnStatement,
    UnaryExpression,
    VariableDeclaration,
    VariableExpression,
    WhileStatement,
)
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import ParseResult, Parser


def _parse(source: str) -> ParseResult:
    lex_result = Lexer(source).scan_tokens()
    assert not lex_result.has_errors, f"Unexpected lex errors: {lex_result.diagnostics}"
    return Parser(lex_result.tokens).parse()


def test_empty_program() -> None:
    result = _parse("")
    assert not result.has_errors
    assert result.program.declarations == ()


def test_variable_declarations_and_assignments() -> None:
    source = (
        "let a: int = 10;\n"
        "let b: float = 2.5;\n"
        'let c: string = "hi";\n'
        "let d: bool = true;\n"
        "a = 20;\n"
    )
    result = _parse(source)
    assert not result.has_errors
    decls = result.program.declarations
    assert len(decls) == 5

    assert isinstance(decls[0], VariableDeclaration)
    assert decls[0].name == "a"
    assert decls[0].type_annotation.name == "int"
    assert isinstance(decls[0].initializer, LiteralExpression)
    assert decls[0].initializer.value == 10

    assert isinstance(decls[1], VariableDeclaration)
    assert isinstance(decls[1].initializer, LiteralExpression)
    assert decls[1].initializer.value == 2.5

    assert isinstance(decls[2], VariableDeclaration)
    assert isinstance(decls[2].initializer, LiteralExpression)
    assert decls[2].initializer.value == "hi"

    assert isinstance(decls[3], VariableDeclaration)
    assert isinstance(decls[3].initializer, LiteralExpression)
    assert decls[3].initializer.value is True

    assert isinstance(decls[4], AssignmentStatement)
    assert decls[4].name == "a"
    assert isinstance(decls[4].value, LiteralExpression)
    assert decls[4].value.value == 20


def test_operator_precedence_and_left_associativity() -> None:
    result = _parse("let r1: int = 10 + 20 * 2;\nlet r2: int = 20 - 10 - 5;\n")
    assert not result.has_errors

    r1 = result.program.declarations[0]
    assert isinstance(r1, VariableDeclaration)
    add_expr = r1.initializer
    assert isinstance(add_expr, BinaryExpression)
    assert add_expr.operator.lexeme == "+"
    assert isinstance(add_expr.left, LiteralExpression)
    assert add_expr.left.value == 10
    assert isinstance(add_expr.right, BinaryExpression)
    assert add_expr.right.operator.lexeme == "*"
    assert isinstance(add_expr.right.left, LiteralExpression)
    assert add_expr.right.left.value == 20
    assert isinstance(add_expr.right.right, LiteralExpression)
    assert add_expr.right.right.value == 2

    r2 = result.program.declarations[1]
    assert isinstance(r2, VariableDeclaration)
    outer_sub = r2.initializer
    assert isinstance(outer_sub, BinaryExpression)
    assert outer_sub.operator.lexeme == "-"
    assert isinstance(outer_sub.left, BinaryExpression)
    assert outer_sub.left.operator.lexeme == "-"
    assert isinstance(outer_sub.left.left, LiteralExpression)
    assert outer_sub.left.left.value == 20
    assert isinstance(outer_sub.left.right, LiteralExpression)
    assert outer_sub.left.right.value == 10
    assert isinstance(outer_sub.right, LiteralExpression)
    assert outer_sub.right.value == 5


def test_unary_grouping_comparison_and_logical_precedence() -> None:
    source = "let ok: bool = not (a + -b * 2 < 10) and c == 1 or false;\n"
    result = _parse(source)
    assert not result.has_errors

    decl = result.program.declarations[0]
    assert isinstance(decl, VariableDeclaration)
    or_expr = decl.initializer
    assert isinstance(or_expr, BinaryExpression)
    assert or_expr.operator.lexeme == "or"
    assert isinstance(or_expr.right, LiteralExpression)
    assert or_expr.right.value is False

    and_expr = or_expr.left
    assert isinstance(and_expr, BinaryExpression)
    assert and_expr.operator.lexeme == "and"

    not_expr = and_expr.left
    assert isinstance(not_expr, UnaryExpression)
    assert not_expr.operator.lexeme == "not"
    assert isinstance(not_expr.operand, GroupingExpression)

    eq_expr = and_expr.right
    assert isinstance(eq_expr, BinaryExpression)
    assert eq_expr.operator.lexeme == "=="


def test_if_else_while_blocks_and_print() -> None:
    source = (
        "if (x > 0) {\n"
        "    if (x == 1) {\n"
        "        print(x);\n"
        "    }\n"
        "} else {\n"
        "    while (y < 5) {\n"
        "        {\n"
        "            y = y + 1;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = _parse(source)
    assert not result.has_errors

    if_stmt = result.program.declarations[0]
    assert isinstance(if_stmt, IfStatement)
    assert isinstance(if_stmt.then_branch, BlockStatement)
    assert isinstance(if_stmt.then_branch.statements[0], IfStatement)
    assert isinstance(if_stmt.else_branch, BlockStatement)

    while_stmt = if_stmt.else_branch.statements[0]
    assert isinstance(while_stmt, WhileStatement)
    assert isinstance(while_stmt.body.statements[0], BlockStatement)

    inner_if = if_stmt.then_branch.statements[0]
    assert isinstance(inner_if, IfStatement)
    assert isinstance(inner_if.then_branch.statements[0], PrintStatement)


def test_functions_calls_and_return_statements() -> None:
    source = (
        "fn add(a: int, b: int) -> int {\n"
        "    return a + b;\n"
        "}\n"
        "fn ping() -> void {\n"
        "    return;\n"
        "}\n"
        "let x: int = add(1, add(2, 3));\n"
        "ping();\n"
    )
    result = _parse(source)
    assert not result.has_errors
    decls = result.program.declarations
    assert len(decls) == 4

    fn_add = decls[0]
    assert isinstance(fn_add, FunctionDeclaration)
    assert fn_add.name == "add"
    assert [p.name for p in fn_add.params] == ["a", "b"]
    assert fn_add.return_type.name == "int"
    assert isinstance(fn_add.body.statements[0], ReturnStatement)
    assert fn_add.body.statements[0].value is not None

    fn_ping = decls[1]
    assert isinstance(fn_ping, FunctionDeclaration)
    assert fn_ping.params == ()
    assert fn_ping.return_type.name == "void"
    ret_void = fn_ping.body.statements[0]
    assert isinstance(ret_void, ReturnStatement)
    assert ret_void.value is None

    var_x = decls[2]
    assert isinstance(var_x, VariableDeclaration)
    assert isinstance(var_x.initializer, FunctionCallExpression)
    assert len(var_x.initializer.arguments) == 2
    assert isinstance(var_x.initializer.arguments[1], FunctionCallExpression)

    expr_stmt = decls[3]
    assert isinstance(expr_stmt, ExpressionStatement)
    assert isinstance(expr_stmt.expression, FunctionCallExpression)
    assert expr_stmt.expression.callee == "ping"


def test_nested_function_declaration_is_rejected() -> None:
    source = (
        "fn outer() -> void {\n"
        "    fn inner() -> void {\n"
        "        return;\n"
        "    }\n"
        "}\n"
    )
    result = _parse(source)
    assert result.has_errors
    assert any("Nested function" in d.message for d in result.diagnostics)


def test_parser_error_recovery_collects_multiple_errors() -> None:
    source = (
        "let a: int = 10\n"
        "let b: int = 20;\n"
        "fn broken(x int) -> {\n"
        "    return x;\n"
        "}\n"
        "let c: int = ;\n"
        "let d: int = 30;\n"
    )
    result = _parse(source)

    assert result.has_errors
    assert len(result.diagnostics) >= 3
    assert all(d.phase is DiagnosticPhase.PARSER for d in result.diagnostics)

    valid_var_names = [
        d.name for d in result.program.declarations if isinstance(d, VariableDeclaration)
    ]
    assert "b" in valid_var_names
    assert "d" in valid_var_names


def test_missing_braces_and_invalid_expressions() -> None:
    source = "if (true) print(1); let x: int = +;"
    result = _parse(source)
    assert result.has_errors
    assert len(result.diagnostics) >= 2
