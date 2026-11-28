from __future__ import annotations

import pytest

from rifai.compiler import Compiler
from rifai.frontend.ast_nodes import AssignmentStatement, ForStatement, VariableDeclaration
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.vm import VirtualMachine


def _parse_and_analyze(source: str):
    lexical = Lexer(source).scan_tokens()
    assert not lexical.has_errors, lexical.diagnostics
    parsed = Parser(lexical.tokens).parse()
    assert not parsed.has_errors, parsed.diagnostics
    semantic = SemanticAnalyzer().analyze(parsed.program)
    return parsed.program, semantic


@pytest.mark.parametrize("optimize", [False, True])
def test_for_break_continue_and_short_circuit_execution(optimize: bool):
    source = """\
let visits: int = 0;
fn visit() -> bool {
    visits = visits + 1;
    return true;
}
let skipped_and: bool = false and visit();
let skipped_or: bool = true or visit();
let evaluated: bool = true and visit();
print(skipped_and);
print(skipped_or);
print(visits);
let sum: int = 0;
for (let i: int = 0; i < 10; i = i + 1) {
    if (i == 2) { continue; }
    sum = sum + i;
    if (sum >= 10) { break; }
}
print(sum);
let n: int = 0;
let odd_sum: int = 0;
while (n < 6) {
    n = n + 1;
    if (n % 2 == 0) { continue; }
    odd_sum = odd_sum + n;
}
print(odd_sum);
"""
    result = Compiler(optimize=optimize).compile(source)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    assert result.module.format_version == 5
    execution = VirtualMachine().execute(result.module)
    assert execution.output == ("false", "true", "1", "13", "9")


def test_for_loop_supports_omitted_clauses_and_break():
    source = """\
let i: int = 0;
for (; ; i = i + 1) {
    if (i == 3) { break; }
}
print(i);
"""
    result = Compiler().compile(source)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    assert VirtualMachine().execute(result.module).output == ("3",)


def test_nested_loop_control_targets_the_innermost_loop():
    source = """\
let total: int = 0;
for (let i: int = 0; i < 3; i = i + 1) {
    let j: int = 0;
    while (j < 4) {
        j = j + 1;
        if (j == 2) { continue; }
        if (j == 4) { break; }
        total = total + 1;
    }
}
print(total);
"""
    result = Compiler().compile(source)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    assert VirtualMachine().execute(result.module).output == ("6",)


def test_continue_in_for_runs_increment_clause():
    source = """\
let updates: int = 0;
for (let i: int = 0; i < 5; i = i + 1) {
    if (i < 4) { continue; }
    updates = updates + 1;
}
print(updates);
"""
    result = Compiler(optimize=False).compile(source)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    assert VirtualMachine().execute(result.module).output == ("1",)


def test_short_circuit_skips_runtime_traps_and_nested_calls():
    source = """\
let called: int = 0;
fn mark() -> bool {
    called = called + 1;
    return true;
}
print(false and (1 / 0 > 0));
print(true or (1 / 0 > 0));
print(false and (true or mark()));
print(true or (false and mark()));
print(called);
"""
    result = Compiler(optimize=False).compile(source)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    assert VirtualMachine().execute(result.module).output == (
        "false", "true", "false", "true", "0"
    )


def test_for_initializer_variable_is_scoped_to_loop():
    _, semantic = _parse_and_analyze(
        "for (let index: int = 0; index < 1; index = index + 1) { print(index); }"
    )
    assert semantic.is_valid, semantic.diagnostics

    result = Compiler().compile(
        "for (let index: int = 0; index < 1; index = index + 1) { print(index); } "
        "print(index);"
    )
    assert not result.is_success
    assert any("Undefined variable 'index'" in item.message for item in result.diagnostics)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("break;", "'break' is only allowed inside a loop."),
        ("continue;", "'continue' is only allowed inside a loop."),
        ("for (; 1; ) { break; }", "'for' condition must have type 'bool'"),
        ("while (true) { } continue;", "'continue' is only allowed inside a loop."),
    ],
)
def test_invalid_loop_control_and_conditions_are_rejected(source: str, message: str):
    result = Compiler().compile(source)
    assert not result.is_success
    assert any(message in item.message for item in result.diagnostics)


def test_for_loop_parser_and_ast_preserve_clause_structure():
    program, semantic = _parse_and_analyze(
        "for (let i: int = 0; i < 3; i = i + 1) { print(i); }"
    )
    loop = program.declarations[0]
    assert isinstance(loop, ForStatement)
    assert isinstance(loop.initializer, VariableDeclaration)
    assert loop.condition is not None
    assert isinstance(loop.increment, AssignmentStatement)
    assert semantic.is_valid, semantic.diagnostics
