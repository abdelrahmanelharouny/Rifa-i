from __future__ import annotations

from dataclasses import replace

import pytest

from rifai.bytecode import (
    GENERIC_TYPES_FORMAT_VERSION,
    BytecodeSerializer,
    BytecodeVerifier,
)
from rifai.compiler import Compiler
from rifai.frontend.ast_nodes import EnumDeclaration, FunctionDeclaration, StructDeclaration
from rifai.frontend.generics import GenericSpecializer
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.ir import BytecodeToIR, IRToBytecode, IRVerifier
from rifai.vm import VirtualMachine


SOURCE = """\
struct Box<T: Display> {
    value: T,
}

struct Point {
    x: int,
}

enum Option<T: Display> {
    Some(T),
    None,
}

fn identity<T>(value: T) -> T {
    return value;
}

fn first<T: ArrayElement>(values: T[]) -> T {
    return values[0];
}

fn first_row<T: ArrayElement>(values: T[][]) -> T[] {
    return values[0];
}

fn describe<T: Display>(option: Option<T>) -> string {
    return match (option) {
        Option.Some(value) => to_string(value),
        Option.None => "none",
    };
}

fn add<T: Addable>(left: T, right: T) -> T {
    return left + right;
}

fn equal<T: Equatable>(left: T, right: T) -> bool {
    return left == right;
}

let inferred_box = Box(42);
let explicit_box: Box<string> = Box<string>("rifai");
let boxes: Box<int>[] = [Box<int>(1), Box(2)];
let points: Point[] = [Point(3), Point(5)];
let matrix: int[][] = [[1, 2], [3, 4]];
let matrix_copy: int[][] = first_row(matrix);
let nested_empty: int[][] = [[], []];
let some: Option<int> = Option<int>.Some(9);
let none: Option<string> = Option<string>.None;

print(to_string(inferred_box.value));
print(explicit_box.value);
print(to_string(first(boxes).value));
print(to_string(first(points).x));
print(to_string(matrix_copy[1][0]));
print(to_string(len(nested_empty[0])));
print(describe(some));
print(describe(none));
print(add<int>(4, 6));
print(add("ri", "fai"));
print(equal(some, some));
print(identity<int[]>([])[0]);
"""


def _compile(source: str, *, optimize: bool = False):
    result = Compiler(optimize=optimize).compile(source, source_name="phase19.rif")
    assert result.is_success, result.diagnostics
    assert result.module is not None
    return result


@pytest.mark.parametrize("optimize", [False, True])
def test_generic_structs_enums_bounds_explicit_arguments_and_recursive_arrays(optimize: bool):
    compiled = _compile(SOURCE, optimize=optimize)
    assert compiled.module.format_version == GENERIC_TYPES_FORMAT_VERSION == 7
    assert VirtualMachine().execute(compiled.module).output == (
        "42",
        "rifai",
        "1",
        "3",
        "3",
        "0",
        "9",
        "none",
        "10",
        "rifai",
        "true",
        "0",
    )


def test_generic_declarations_are_monomorphized_and_templates_removed():
    lexical = Lexer(
        "struct Box<T: Display> { value: T } "
        "enum Option<T> { Some(T), None } "
        "fn id<T: Copy>(x: T) -> T { return x; } "
        "let x = Box<int>(1); let y = Option<int>.Some(2); let z = id<int>(3);"
    ).scan_tokens()
    assert not lexical.has_errors, lexical.diagnostics
    parsed = Parser(lexical.tokens).parse()
    assert not parsed.has_errors, parsed.diagnostics
    assert isinstance(parsed.program.declarations[0], StructDeclaration)
    assert isinstance(parsed.program.declarations[1], EnumDeclaration)
    assert isinstance(parsed.program.declarations[2], FunctionDeclaration)

    specialized = GenericSpecializer().specialize(parsed.program)
    assert specialized.is_valid, specialized.diagnostics
    assert not any(
        getattr(declaration, "type_parameters", ())
        for declaration in specialized.program.declarations
        if isinstance(declaration, (StructDeclaration, EnumDeclaration, FunctionDeclaration))
    )
    assert any(
        isinstance(declaration, StructDeclaration)
        and declaration.name.startswith("__rifai_generic_type_Box_")
        for declaration in specialized.program.declarations
    )
    assert any(
        isinstance(declaration, EnumDeclaration)
        and declaration.name.startswith("__rifai_generic_type_Option_")
        for declaration in specialized.program.declarations
    )


def test_generic_collection_operations_reach_vm_and_survive_ir_bytecode_round_trip():
    source = """\
struct Item { value: int }
let nested: Item[][] = [[Item(4)], [Item(8)]];
push(nested[0], Item(6));
nested[1][0] = Item(10);
print(to_string(nested[0][1].value));
print(to_string(nested[1][0].value));
"""
    compiled = _compile(source)
    assert any(
        instruction.opcode.value == "ARRAY_NEW_TYPED"
        for instruction in compiled.module.main.instructions
    )
    encoded = BytecodeSerializer.to_bytes(compiled.module)
    restored = BytecodeSerializer.from_bytes(encoded)
    assert restored == compiled.module
    assert BytecodeVerifier().verify(restored).is_valid
    expected = ("6", "10")
    assert VirtualMachine().execute(restored).output == expected

    lifted = BytecodeToIR().build(restored)
    assert IRVerifier().verify(lifted).is_valid
    relowered = IRToBytecode().lower(lifted)
    assert BytecodeVerifier().verify(relowered).is_valid
    assert VirtualMachine().execute(relowered).output == expected


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "fn numeric<T: Numeric>(value: T) -> T { return value; } "
            "let invalid = numeric(true);",
            "does not satisfy constraint 'Numeric'",
        ),
        (
            "fn ordered<T: Ordered>(value: T) -> T { return value; } "
            "let invalid = ordered(false);",
            "does not satisfy constraint 'Ordered'",
        ),
        (
            "fn invalid<T: MadeUp>(value: T) -> T { return value; }",
            "Unknown type constraint 'MadeUp'",
        ),
        (
            "struct Box<T: Numeric> { value: T } "
            "let invalid = Box<string>(\"text\");",
            "does not satisfy constraint 'Numeric'",
        ),
        (
            "fn id<T>(value: T) -> T { return value; } "
            "let invalid = id<int, string>(1);",
            "expects 1 explicit type argument(s), got 2",
        ),
    ],
)
def test_type_constraints_and_explicit_argument_errors_are_diagnostic(source: str, message: str):
    result = Compiler().compile(source)
    assert not result.is_success
    assert any(message in item.message for item in result.diagnostics)


def test_nested_array_and_nominal_array_mismatches_are_rejected():
    sources = (
        "struct Point { x: int } let bad: Point[] = [Point(1), 2];",
        "let bad: int[][] = [[1], [true]];",
        "let bad: int[][] = [[1], \"not an array\"];",
        "struct Box<T> { value: T } let bad: Box<int>[] = [Box<string>(\"x\")];",
    )
    for source in sources:
        result = Compiler().compile(source)
        assert not result.is_success, source


def test_generic_struct_nominal_arrays_and_nested_empty_arrays_accept_expected_types():
    source = """\
struct Box<T> { value: T }
let boxes: Box<int>[] = [];
push(boxes, Box<int>(12));
let nested: int[][] = [[], [1, 2]];
print(to_string(boxes[0].value));
print(to_string(len(nested[0])));
print(to_string(nested[1][1]));
"""
    compiled = _compile(source)
    assert VirtualMachine().execute(compiled.module).output == ("12", "0", "2")


def test_bytecode_v6_compatibility_and_v7_opcode_version_gate():
    compiled = _compile("let values: int[] = [1, 2]; print(values[1]);")
    assert compiled.module.format_version == 7
    legacy = replace(compiled.module, format_version=6)
    assert BytecodeVerifier().verify(legacy).is_valid
    restored = BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(legacy))
    assert restored.format_version == 6
    assert VirtualMachine().execute(restored).output == ("2",)

    typed = _compile("struct Point { x: int } let points: Point[] = [Point(1)];")
    v6_typed = replace(typed.module, format_version=6)
    validation = BytecodeVerifier().verify(v6_typed)
    assert not validation.is_valid
    assert any("ARRAY_NEW_TYPED requires bytecode version 7" in item.message for item in validation.diagnostics)
