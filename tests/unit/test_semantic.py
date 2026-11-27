"""Comprehensive unit tests for the Rifa'i SemanticAnalyzer."""

from __future__ import annotations

import pytest

from rifai.errors.diagnostics import DiagnosticPhase
from rifai.frontend.ast_nodes import (
    FunctionCallExpression,
    FunctionDeclaration,
    VariableDeclaration,
)
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer, SemanticResult
from rifai.frontend.types import RifaiType


def _analyze(source: str) -> SemanticResult:
    lex = Lexer(source).scan_tokens()
    assert not lex.has_errors, f"Unexpected lex errors: {lex.diagnostics}"
    parsed = Parser(lex.tokens).parse()
    assert not parsed.has_errors, f"Unexpected parse errors: {parsed.diagnostics}"
    return SemanticAnalyzer().analyze(parsed.program)


def test_valid_declarations_and_semantic_model_bindings() -> None:
    source = (
        "fn add(a: int, b: int) -> int { return a + b; }\n"
        "let x: int = add(1, 2);\n"
        "let y: float = 1.5 + 2.5;\n"
        "let ok: bool = true and not false;\n"
        'let msg: string = "hi" + "!";\n'
    )
    lex = Lexer(source).scan_tokens()
    parsed = Parser(lex.tokens).parse()
    sem = SemanticAnalyzer().analyze(parsed.program)

    assert sem.is_valid
    fn_decl = parsed.program.declarations[0]
    var_x = parsed.program.declarations[1]
    assert isinstance(fn_decl, FunctionDeclaration)
    assert isinstance(var_x, VariableDeclaration)
    assert isinstance(var_x.initializer, FunctionCallExpression)

    fn_sym = sem.function_for(fn_decl)
    assert fn_sym is not None
    assert fn_sym.return_type is RifaiType.INT
    assert sem.function_for(var_x.initializer) is fn_sym
    assert sem.type_of(var_x.initializer) is RifaiType.INT

    var_sym = sem.variable_for(var_x)
    assert var_sym is not None
    assert var_sym.rifai_type is RifaiType.INT
    assert var_sym.is_global is True


def test_undefined_variable_and_undefined_function() -> None:
    res = _analyze("print(missing);\nunknown_fn(1);\n")
    assert not res.is_valid
    assert len(res.diagnostics) == 2
    assert all(d.phase is DiagnosticPhase.SEMANTIC for d in res.diagnostics)


def test_duplicate_variables_functions_and_parameters() -> None:
    res = _analyze(
        "let x: int = 1;\n"
        "let x: int = 2;\n"
        "fn f(a: int, a: float) -> void { return; }\n"
        "fn f() -> void { return; }\n"
    )
    assert not res.is_valid
    assert len(res.diagnostics) == 3


def test_parameter_cannot_be_redeclared_in_function_outer_body() -> None:
    res = _analyze("fn f(a: int) -> void { let a: int = 10; }\n")
    assert not res.is_valid
    assert "Duplicate declaration" in res.diagnostics[0].message


def test_void_rejected_for_variables_parameters_and_print() -> None:
    res = _analyze(
        "let v: void = 1;\n"
        "fn f(p: void) -> void { return; }\n"
        "fn g() -> void { return; }\n"
        "print(g());\n"
    )
    assert not res.is_valid
    assert len(res.diagnostics) >= 3


def test_strict_typing_and_invalid_initializers_or_assignments() -> None:
    res = _analyze(
        "let a: int = 10.5;\n"
        "let b: float = 20;\n"
        "let c: int = 5;\n"
        'c = "bad";\n'
    )
    assert not res.is_valid
    assert len(res.diagnostics) == 3


def test_arithmetic_rules_strict() -> None:
    valid = _analyze(
        "let i1: int = 1 + 2 - 3 * 4 % 5;\n"
        "let f1: float = 1.0 + 2.0 - 3.0 * 4.0;\n"
        "let d1: float = 10 / 2;\n"
        "let d2: float = 10.0 / 2.0;\n"
        'let s1: string = "a" + "b";\n'
    )
    assert valid.is_valid

    invalid = _analyze(
        "let m1: float = 1 + 2.0;\n"
        "let m2: float = 1.0 % 2.0;\n"
        "let m3: int = 10 / 2;\n"
        'let m4: string = "a" - "b";\n'
        "let m5: bool = true + false;\n"
    )
    assert not invalid.is_valid
    assert len(invalid.diagnostics) == 5


def test_comparison_and_equality_rules() -> None:
    valid = _analyze(
        "let b1: bool = 1 < 2 and 2.0 >= 1.0;\n"
        'let b2: bool = "a" == "a" and true != false;\n'
    )
    assert valid.is_valid

    invalid = _analyze(
        "let e1: bool = 1 < 2.0;\n"
        'let e2: bool = "a" < "b";\n'
        "let e3: bool = true < false;\n"
        "let e4: bool = 1 == 1.0;\n"
        'let e5: bool = 1 != "1";\n'
    )
    assert not invalid.is_valid
    assert len(invalid.diagnostics) == 5


def test_logical_and_unary_operator_rules() -> None:
    valid = _analyze(
        "let a: int = -5;\n"
        "let b: float = -2.5;\n"
        "let c: bool = not (true and false or true);\n"
    )
    assert valid.is_valid

    invalid = _analyze(
        "let x: bool = 10 and true;\n"
        'let y: bool = "a" or false;\n'
        "let z: int = not 1;\n"
        "let w: bool = -true;\n"
    )
    assert not invalid.is_valid
    assert len(invalid.diagnostics) == 4


def test_if_while_conditions_must_be_bool() -> None:
    res = _analyze("if (1) { print(1); }\nwhile (\"x\") { print(2); }\n")
    assert not res.is_valid
    assert len(res.diagnostics) == 2


def test_function_calls_args_and_void_as_value() -> None:
    res = _analyze(
        "fn add(a: int, b: int) -> int { return a + b; }\n"
        "fn noop() -> void { return; }\n"
        "let x: int = add(1);\n"
        'let y: int = add(1, "two");\n'
        "let z: int = noop();\n"
        "let n: int = 5;\n"
        "n();\n"
    )
    assert not res.is_valid
    assert len(res.diagnostics) == 4


def test_return_rules_and_definite_return_analysis() -> None:
    valid = _analyze(
        "fn abs_val(n: int) -> int {\n"
        "    if (n < 0) {\n"
        "        return -n;\n"
        "    } else {\n"
        "        return n;\n"
        "    }\n"
        "}\n"
        "fn v() -> void { print(1); }\n"
    )
    assert valid.is_valid

    invalid = _analyze(
        "return 1;\n"
        "fn bad_void() -> void { return 42; }\n"
        "fn missing_expr() -> int { return; }\n"
        "fn wrong_type() -> int { return 1.5; }\n"
        "fn while_ret() -> int { while (true) { return 1; } }\n"
        "fn if_no_else() -> int { if (true) { return 1; } }\n"
    )
    assert not invalid.is_valid
    assert len(invalid.diagnostics) >= 6


def test_nested_scope_shadowing_and_global_function_var_conflicts() -> None:
    valid = _analyze(
        "let x: int = 10;\n"
        "if (true) {\n"
        "    let x: string = \"inner\";\n"
        "    print(x);\n"
        "}\n"
        "print(x + 1);\n"
    )
    assert valid.is_valid

    conflict = _analyze(
        "fn foo() -> void { return; }\n"
        "let foo: int = 5;\n"
    )
    assert not conflict.is_valid
    assert "conflicts" in conflict.diagnostics[0].message


def test_forward_function_reference_and_mutual_recursion() -> None:
    res = _analyze(
        "fn is_even(n: int) -> bool {\n"
        "    if (n == 0) { return true; }\n"
        "    return is_odd(n - 1);\n"
        "}\n"
        "fn is_odd(n: int) -> bool {\n"
        "    if (n == 0) { return false; }\n"
        "    return is_even(n - 1);\n"
        "}\n"
        "print(is_even(4));\n"
    )
    assert res.is_valid


def test_global_variables_are_not_hoisted() -> None:
    res = _analyze(
        "fn f() -> int { return g; }\n"
        "let g: int = 10;\n"
    )
    assert not res.is_valid
    assert "Undefined variable 'g'" in res.diagnostics[0].message
