from __future__ import annotations

from dataclasses import replace

import pytest

from rifai.bytecode import (
    ALGEBRAIC_TYPES_FORMAT_VERSION,
    BytecodeSerializer,
    BytecodeVerifier,
)
from rifai.compiler import Compiler
from rifai.frontend.ast_nodes import EnumConstructorExpression, EnumDeclaration, MatchExpression
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.ir import BytecodeToIR, IRToBytecode, IRVerifier
from rifai.vm import VirtualMachine


def _frontend(source: str):
    lexical = Lexer(source).scan_tokens()
    assert not lexical.has_errors, lexical.diagnostics
    parsed = Parser(lexical.tokens).parse()
    assert not parsed.has_errors, parsed.diagnostics
    semantic = SemanticAnalyzer().analyze(parsed.program)
    return parsed.program, semantic


def _compile(source: str, *, optimize: bool = False):
    result = Compiler(optimize=optimize).compile(source)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    return result


PROGRAM = """\
enum Result {
    Ok(int),
    Error(string),
    Pair(int, string),
    Empty,
}

fn describe(result: Result) -> string {
    return match (result) {
        Result.Ok(value) => "value=" + to_string(value),
        Result.Error(message) => "error=" + message,
        Result.Pair(number, label) => label + to_string(number),
        Result.Empty => "empty",
    };
}

print(describe(Result.Ok(42)));
print(describe(Result.Error("offline")));
print(describe(Result.Pair(7, "items")));
print(describe(Result.Empty));
let fallback: string = match (Result.Ok(9)) {
    Result.Error(message) => message,
    _ => "fallback",
};
print(fallback);
"""


@pytest.mark.parametrize("optimize", [False, True])
def test_payload_enums_exhaustive_match_and_wildcard_execute(optimize: bool):
    result = _compile(PROGRAM, optimize=optimize)
    assert result.module.format_version == ALGEBRAIC_TYPES_FORMAT_VERSION == 6
    assert VirtualMachine().execute(result.module).output == (
        "value=42", "error=offline", "items7", "empty", "fallback"
    )


def test_match_parser_ast_and_enum_constructor_nodes():
    program, semantic = _frontend(PROGRAM)
    assert semantic.is_valid, semantic.diagnostics
    enum = next(item for item in program.declarations if isinstance(item, EnumDeclaration))
    assert [item.name for item in enum.variants] == ["Ok", "Error", "Pair", "Empty"]
    assert [len(item.payload_types) for item in enum.variants] == [1, 1, 2, 0]

    constructors = []
    matches = []
    def visit(node):
        if isinstance(node, EnumConstructorExpression):
            constructors.append(node)
        if isinstance(node, MatchExpression):
            matches.append(node)
        from rifai.frontend.ast_nodes import _node_children
        for _, child in _node_children(node):
            visit(child)
    for declaration in program.declarations:
        visit(declaration)
    assert len(constructors) >= 4
    assert len(matches) >= 2


def test_match_payload_bindings_are_scoped_to_their_arm():
    source = """\
enum Option { Some(int), None }
let selected = Option.Some(10);
let value: int = match (selected) {
    Option.Some(payload) => payload,
    Option.None => 0,
};
print(value);
"""
    result = _compile(source)
    assert VirtualMachine().execute(result.module).output == ("10",)

    escaped = Compiler().compile(source + "print(payload);")
    assert not escaped.is_success
    assert any("Undefined variable 'payload'" in item.message for item in escaped.diagnostics)


def test_nested_nominal_payloads_and_nested_match_expressions():
    source = """\
struct User { name: string }
enum Lookup { Found(User), Missing }
enum Result { Ok(int), Error(string) }
let lookup = Lookup.Found(User("Ada"));
let rendered: string = match (lookup) {
    Lookup.Found(user) => match (Result.Ok(len(user.name))) {
        Result.Ok(size) => user.name + ":" + to_string(size),
        Result.Error(message) => message,
    },
    Lookup.Missing => "missing",
};
print(rendered);
"""
    result = _compile(source)
    assert VirtualMachine().execute(result.module).output == ("Ada:3",)


def test_enum_payload_values_are_immutable_and_formatted():
    source = """\
enum Result { Ok(int), Error(string) }
let result = Result.Ok(3);
print(to_string(result));
"""
    result = _compile(source)
    assert VirtualMachine().execute(result.module).output == ("Result.Ok(3)",)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "enum Result { Ok(int), Error(string) } let x = match (Result.Ok(1)) { Result.Ok(v) => v };",
            "Non-exhaustive match",
        ),
        (
            "enum Result { Ok(int), Error(string) } let x = match (Result.Ok(1)) { Result.Ok(v) => v, Result.Ok(w) => w, Result.Error(e) => 0 };",
            "Duplicate match arm",
        ),
        (
            "enum Result { Ok(int), Error(string) } let x = match (Result.Ok(1)) { _ => 0, Result.Error(e) => 1 };",
            "wildcard match arm must be the final arm",
        ),
        (
            "enum Result { Ok(int), Error(string) } let x = match (Result.Ok(1)) { Result.Ok() => 0, Result.Error(e) => 1 };",
            "expects 1 binding(s), got 0",
        ),
        (
            "enum Result { Ok(int), Error(string) } let x = match (Result.Ok(1)) { Result.Ok(v) => v, Result.Error(e) => e };",
            "Match arm type mismatch",
        ),
        (
            "enum Result { Ok(int), Error(string) } let x = match (1) { Result.Ok(v) => v, Result.Error(e) => 0 };",
            "'match' requires an enum value",
        ),
        (
            "enum Result { Ok(int), Error(string) } let x = Result.Ok(\"wrong\");",
            "expects 'int'",
        ),
        (
            "enum Result { Ok(int), Error(string) } let x = Result.Ok();",
            "expects 1 payload value(s)",
        ),
        (
            "enum Result { Ok(int) } let x = match (Result.Ok(1)) { Other.Ok(v) => v };",
            "does not match subject enum",
        ),
    ],
)
def test_semantic_rejections_for_payloads_and_patterns(source: str, message: str):
    result = Compiler().compile(source)
    assert not result.is_success
    assert any(message in item.message for item in result.diagnostics)


def test_v6_bytecode_roundtrip_and_ir_lifting_preserve_match_behavior():
    result = _compile(PROGRAM)
    encoded = BytecodeSerializer.to_bytes(result.module)
    restored = BytecodeSerializer.from_bytes(encoded)
    assert restored == result.module
    assert BytecodeVerifier().verify(restored).is_valid
    assert VirtualMachine().execute(restored).output == (
        "value=42", "error=offline", "items7", "empty", "fallback"
    )

    lifted = BytecodeToIR().build(restored)
    assert IRVerifier().verify(lifted).is_valid
    lowered = IRToBytecode().lower(lifted)
    assert lowered.format_version == 6
    assert VirtualMachine().execute(lowered).output == VirtualMachine().execute(restored).output


def test_v5_bytecode_is_still_readable_and_new_opcodes_are_version_gated():
    from rifai.bytecode import BytecodeModule, CodeChunk, Instruction, Opcode

    legacy_v5 = BytecodeModule(
        constants=(),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.ENUM_NEW, "State|Ready,Locked|Ready"),
                Instruction(Opcode.POP),
                Instruction(Opcode.HALT),
            ),
        ),
        format_version=5,
    )
    assert BytecodeVerifier().verify(legacy_v5).is_valid
    assert BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(legacy_v5)) == legacy_v5

    new_opcode_v5 = replace(
        legacy_v5,
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.ENUM_NEW_PAYLOAD, "Result|Ok|int"),
                Instruction(Opcode.POP),
                Instruction(Opcode.HALT),
            ),
        ),
    )
    validation = BytecodeVerifier().verify(new_opcode_v5)
    assert not validation.is_valid
    assert any("requires bytecode version 6" in item.message for item in validation.diagnostics)
