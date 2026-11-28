from __future__ import annotations

import pytest

from rifai.compiler import Compiler
from rifai.frontend.ast_nodes import FunctionDeclaration
from rifai.frontend.generics import GenericSpecializer
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.vm import VirtualMachine


SOURCE = """\
struct Box { value: int }
enum Maybe { Some(int), None }

fn identity<T>(value: T) -> T {
    let copy: T = value;
    return copy;
}

fn first<T>(items: T[]) -> T {
    return items[0];
}

fn relay<T>(value: T) -> T {
    return identity(value);
}

fn combine<T>(left: T, right: T) -> T {
    return left + right;
}

let number = relay(identity(42));
let text = identity("generic");
let values = [2, 4, 8];
let head = first(values);
let boxed = identity(Box(7));
let maybe = identity(Maybe.Some(9));
print(to_string(number));
print(text);
print(to_string(head));
print(to_string(boxed.value));
print(match (maybe) {
    Maybe.Some(value) => to_string(value),
    Maybe.None => "none",
});
print(combine(4, 6));
"""


def _compile(source: str, *, optimize: bool = False):
    result = Compiler(optimize=optimize).compile(source)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    return result


@pytest.mark.parametrize("optimize", [False, True])
def test_generic_functions_infer_primitive_array_and_nominal_types(optimize: bool):
    result = _compile(SOURCE, optimize=optimize)
    assert VirtualMachine().execute(result.module).output == (
        "42", "generic", "2", "7", "9", "10"
    )
    names = [function.name for function in result.module.functions]
    identity_instances = [name for name in names if name.startswith("__rifai_generic_identity_")]
    assert len(identity_instances) == 4
    assert len(identity_instances) == len(set(identity_instances))


def test_generic_function_ast_and_specializer_remove_templates():
    lexed = Lexer("fn identity<T>(value: T) -> T { return value; } let x = identity(1);").scan_tokens()
    assert not lexed.has_errors
    parsed = Parser(lexed.tokens).parse()
    assert not parsed.has_errors
    declaration = parsed.program.declarations[0]
    assert isinstance(declaration, FunctionDeclaration)
    assert [item.lexeme for item in declaration.type_parameters] == ["T"]
    assert declaration.params[0].type_annotation.name == "T"

    result = GenericSpecializer().specialize(parsed.program)
    assert result.is_valid, result.diagnostics
    functions = [item for item in result.program.declarations if isinstance(item, FunctionDeclaration)]
    assert len(functions) == 1
    assert functions[0].type_parameters == ()
    assert functions[0].params[0].type_annotation.name == "int"


def test_nested_generic_calls_share_cached_specializations_and_allow_recursion():
    source = """\
fn identity<T>(value: T) -> T { return identity_inner(value); }
fn identity_inner<T>(value: T) -> T { return value; }
fn relay<T>(value: T) -> T { return identity(value); }
fn recurse<T>(value: T) -> T {
    if (true) { return value; } else { return recurse(value); }
}
print(to_string(relay(31)));
print(to_string(recurse(11)));
"""
    result = _compile(source)
    assert VirtualMachine().execute(result.module).output == ("31", "11")
    names = [function.name for function in result.module.functions]
    assert sum(
        name.startswith("__rifai_generic_identity_")
        and not name.startswith("__rifai_generic_identity_inner_")
        for name in names
    ) == 1
    assert sum(name.startswith("__rifai_generic_identity_inner_") for name in names) == 1


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "fn same<T>(left: T, right: T) -> T { return left; } let x = same(1, \"x\");",
            "Conflicting inferences for 'T'",
        ),
        (
            "fn first<T>(items: T[]) -> T { return items[0]; } let x = first([]);",
            "Cannot infer generic type parameter 'T'",
        ),
        (
            "fn impossible<T>(value: int) -> T { return value; }",
            "must appear in a parameter type",
        ),
    ],
)
def test_invalid_generic_inference_reports_semantic_diagnostic(source: str, message: str):
    result = Compiler().compile(source)
    assert not result.is_success
    assert any(message in item.message for item in result.diagnostics)


def test_generic_body_is_checked_after_each_concrete_instantiation():
    source = """\
fn add_one<T>(value: T) -> T { return value + 1; }
let answer = add_one("text");
"""
    result = Compiler().compile(source)
    assert not result.is_success
    assert any("Operator '+' is not supported" in item.message for item in result.diagnostics)


def test_generic_array_annotation_requires_supported_primitive_array_after_substitution():
    source = """\
struct Point { x: int }
fn first<T>(items: T[]) -> T { return items[0]; }
let points: Point[] = [Point(1)];
let point = first(points);
"""
    result = Compiler().compile(source)
    assert not result.is_success
    assert any("Unknown type 'Point[]'" in item.message for item in result.diagnostics)
