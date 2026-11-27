"""End-to-end frontend pipeline integration tests (Lexer -> Parser -> SemanticAnalyzer)."""

from __future__ import annotations

from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer, SemanticResult


def _compile_frontend(source: str) -> SemanticResult:
    lex = Lexer(source).scan_tokens()
    assert not lex.has_errors, f"Unexpected lex errors: {lex.diagnostics}"
    parsed = Parser(lex.tokens).parse()
    assert not parsed.has_errors, f"Unexpected parse errors: {parsed.diagnostics}"
    return SemanticAnalyzer().analyze(parsed.program)


def test_integration_basic_program() -> None:
    source = (
        "let x: int = 10;\n"
        "let y: int = 20;\n"
        "let result: int = x + y;\n"
        "print(result);\n"
    )
    assert _compile_frontend(source).is_valid


def test_integration_functions() -> None:
    source = (
        "fn add(a: int, b: int) -> int {\n"
        "    return a + b;\n"
        "}\n"
        "let result: int = add(10, 20);\n"
        "print(result);\n"
    )
    assert _compile_frontend(source).is_valid


def test_integration_recursion() -> None:
    source = (
        "fn factorial(n: int) -> int {\n"
        "    if (n <= 1) {\n"
        "        return 1;\n"
        "    } else {\n"
        "        return n * factorial(n - 1);\n"
        "    }\n"
        "}\n"
        "print(factorial(5));\n"
    )
    assert _compile_frontend(source).is_valid


def test_integration_invalid_type() -> None:
    res = _compile_frontend('let x: int = "wrong";\n')
    assert not res.is_valid
    assert len(res.diagnostics) == 1


def test_integration_invalid_scope() -> None:
    source = (
        "if (true) {\n"
        "    let hidden: int = 10;\n"
        "}\n"
        "print(hidden);\n"
    )
    res = _compile_frontend(source)
    assert not res.is_valid
    assert "Undefined variable 'hidden'" in res.diagnostics[0].message


def test_integration_invalid_return_path() -> None:
    source = (
        "fn calculate() -> int {\n"
        "    if (true) {\n"
        "        return 10;\n"
        "    }\n"
        "}\n"
    )
    res = _compile_frontend(source)
    assert not res.is_valid
    assert "must return a value on all execution paths" in res.diagnostics[0].message


def test_integration_string_concatenation() -> None:
    source = (
        'let first: string = "Hello";\n'
        'let second: string = "Rifa\'i";\n'
        'let message: string = first + " " + second;\n'
        "print(message);\n"
    )
    assert _compile_frontend(source).is_valid
