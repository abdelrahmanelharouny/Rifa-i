from __future__ import annotations

from pathlib import Path

import pytest

from rifai.bytecode import (
    BytecodeFormatError,
    BytecodeModule,
    BytecodeSerializer,
    COLLECTIONS_FORMAT_VERSION,
    FORMAT_VERSION,
)
from rifai.compiler import Compiler
from rifai.frontend.ast_nodes import EnumDeclaration, ImportDeclaration, MemberAssignmentStatement, StructDeclaration, VariableDeclaration
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.ir import BytecodeToIR, IRToBytecode, IRVerifier
from rifai.vm import EnumValue, StructValue, VMRuntimeError, VirtualMachine


def _frontend(source: str):
    lexical = Lexer(source).scan_tokens()
    assert not lexical.has_errors, lexical.diagnostics
    parsed = Parser(lexical.tokens).parse()
    assert not parsed.has_errors, parsed.diagnostics
    semantic = SemanticAnalyzer().analyze(parsed.program)
    return parsed.program, semantic


def _compile(source: str, *, source_name: str | None = None):
    result = Compiler(optimize=False).compile(source, source_name=source_name)
    assert result.is_success, result.diagnostics
    assert result.module is not None
    return result


def test_parser_accepts_import_struct_enum_inference_and_member_access():
    source = """import "models.rif";
struct User { name: string, age: int; }
enum State { Ready, Locked }
let user = User("Ada", 36);
user.age = user.age + 1;
let state = State.Ready;
"""
    parsed, semantic = _frontend(source)
    assert semantic.is_valid, semantic.diagnostics
    assert isinstance(parsed.declarations[0], ImportDeclaration)
    assert isinstance(parsed.declarations[1], StructDeclaration)
    assert isinstance(parsed.declarations[2], EnumDeclaration)
    assert isinstance(parsed.declarations[3], VariableDeclaration)
    assert parsed.declarations[3].type_annotation is None
    assert any(isinstance(item, MemberAssignmentStatement) for item in parsed.declarations)


def test_structs_enums_inferred_locals_and_nominal_function_signatures_execute():
    source = """enum State { Ready, Locked }
struct User { name: string, age: int, state: State }
fn birthday(user: User) -> User {
    user.age = user.age + 1;
    return user;
}
let user = User("Ada", 36, State.Ready);
let updated = birthday(user);
print(updated.name);
print(updated.age);
print(user.age);
print(updated.state == State.Ready);
print(to_string(updated));
"""
    result = _compile(source)
    assert result.module.format_version == FORMAT_VERSION == 5
    execution = VirtualMachine().execute(result.module)
    assert execution.output == (
        "Ada",
        "37",
        "37",
        "true",
        "User{name: Ada, age: 37, state: State.Ready}",
    )


def test_structs_are_reference_values_and_field_reads_are_typed():
    source = """struct Box { value: int }
let first = Box(10);
let second: Box = first;
second.value = 25;
print(first.value);
"""
    result = _compile(source)
    assert VirtualMachine().execute(result.module).output == ("25",)
    runtime_value = VirtualMachine().execute(result.module).globals["first"]
    assert isinstance(runtime_value, StructValue)
    assert runtime_value.fields["value"] == 25


def test_enum_values_are_nominal_immutable_and_comparable():
    source = """enum Status { Ready, Running, Failed }
let current: Status = Status.Running;
print(current == Status.Running);
print(current != Status.Failed);
print(to_string(current));
"""
    result = _compile(source)
    execution = VirtualMachine().execute(result.module)
    assert execution.output == ("true", "true", "Status.Running")
    assert isinstance(execution.globals["current"], EnumValue)


@pytest.mark.parametrize(
    "source",
    [
        'struct User { name: string } let user = User("Ada"); print(user.missing);',
        'enum State { Ready, Locked } let state = State.Unknown;',
        'struct User { age: int } let user = User("not-an-int");',
        'struct Empty { }',
        'enum Empty { }',
        'struct User { age: int, age: int }',
        'struct User { age: void }',
        'struct abs { value: int }',
    ],
)
def test_invalid_nominal_declarations_and_member_operations_are_rejected(source):
    result = Compiler(optimize=False).compile(source)
    assert not result.is_success
    assert result.diagnostics


def test_standard_library_math_string_and_conversion_functions():
    source = """print(abs(-8));
print(min(5, 3));
print(max(5.0, 3.0));
print(sqrt(81));
print(round(2.6));
print(to_int(5.9));
print(to_float(7));
print(contains("Rifa'i", "fa"));
print(starts_with("Rifa'i", "Ri"));
print(ends_with("Rifa'i", "'i"));
print(substring("Rifa'i", 0, 4));
print(to_string(true));
"""
    result = _compile(source)
    assert VirtualMachine().execute(result.module).output == (
        "8", "3", "5.0", "9.0", "3", "5", "7.0",
        "true", "true", "true", "Rifa", "true",
    )


def test_optimized_compilation_supports_intrinsic_standard_library_calls():
    source = """let value = abs(-12);
let magnitude = sqrt(81);
let found = contains("Rifa'i", "fa");
print(value);
print(magnitude);
print(found);
"""
    result = Compiler().compile(source)
    assert result.is_success, result.diagnostics
    assert VirtualMachine().execute(result.module).output == ("12", "9.0", "true")


def test_standard_library_rejects_wrong_static_types_and_arity():
    result = Compiler(optimize=False).compile(
        'print(abs("8")); print(substring("abc", 1)); print(min(1, 2.0));'
    )
    assert not result.is_success
    messages = "\n".join(item.message for item in result.diagnostics)
    assert "abs" in messages
    assert "substring" in messages
    assert "same numeric type" in messages


def test_file_io_is_disabled_by_default_and_can_be_granted_a_project_root(tmp_path: Path):
    source = """print(write_text("notes.txt", "Rifa'i data"));
print(file_exists("notes.txt"));
print(read_text("notes.txt"));
"""
    result = _compile(source, source_name=str(tmp_path / "program.rif"))
    with pytest.raises(VMRuntimeError, match="File I/O is disabled"):
        VirtualMachine().execute(result.module)

    execution = VirtualMachine(
        allow_file_io=True,
        file_root=tmp_path,
    ).execute(result.module)
    assert execution.output == ("true", "true", "Rifa'i data")
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "Rifa'i data"


def test_file_io_rejects_traversal_and_bounds_file_sizes(tmp_path: Path):
    (tmp_path.parent / "secret.txt").write_text("private", encoding="utf-8")
    escape = _compile(
        'print(read_text("../secret.txt"));',
        source_name=str(tmp_path / "program.rif"),
    )
    with pytest.raises(VMRuntimeError, match="must stay inside"):
        VirtualMachine(allow_file_io=True, file_root=tmp_path).execute(escape.module)

    (tmp_path / "large.txt").write_bytes(b"x" * 12)
    read = _compile(
        'print(read_text("large.txt"));',
        source_name=str(tmp_path / "reader.rif"),
    )
    with pytest.raises(VMRuntimeError, match="read limit"):
        VirtualMachine(
            allow_file_io=True,
            file_root=tmp_path,
            max_file_bytes=8,
        ).execute(read.module)


def test_file_io_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside-rifai-secret.txt"
    outside.write_text("private", encoding="utf-8")
    link = tmp_path / "leak.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform.")
    result = _compile(
        'print(read_text("leak.txt"));',
        source_name=str(tmp_path / "program.rif"),
    )
    with pytest.raises(VMRuntimeError, match="escapes"):
        VirtualMachine(allow_file_io=True, file_root=tmp_path).execute(result.module)


def test_imports_resolve_nested_modules_once_and_preserve_source_maps(tmp_path: Path):
    (tmp_path / "models.rif").write_text(
        'struct User { name: string, age: int }\n'
        'fn greeting(name: string) -> string { return "Hello " + name; }\n',
        encoding="utf-8",
    )
    main = tmp_path / "main.rif"
    source = 'import "models.rif";\nlet user = User("Ada", 36);\nprint(greeting(user.name));\n'
    main.write_text(source, encoding="utf-8")

    result = _compile(source, source_name=str(main))
    assert VirtualMachine().execute(result.module).output == ("Hello Ada",)
    assert result.module.debug_info is not None
    assert "// module: models.rif" in result.module.debug_info.source_text
    assert "// module: main.rif" in result.module.debug_info.source_text


def test_imports_are_relative_deduplicated_and_cycle_safe(tmp_path: Path):
    (tmp_path / "shared.rif").write_text("fn shared() -> int { return 42; }\n", encoding="utf-8")
    (tmp_path / "left.rif").write_text('import "shared.rif";\nfn left() -> int { return shared(); }\n', encoding="utf-8")
    (tmp_path / "right.rif").write_text('import "shared.rif";\nfn right() -> int { return shared(); }\n', encoding="utf-8")
    source = 'import "left.rif";\nimport "right.rif";\nprint(left() + right());\n'
    result = _compile(source, source_name=str(tmp_path / "main.rif"))
    assert VirtualMachine().execute(result.module).output == ("84",)

    (tmp_path / "a.rif").write_text('import "b.rif";\n', encoding="utf-8")
    (tmp_path / "b.rif").write_text('import "a.rif";\n', encoding="utf-8")
    cycle = Compiler(optimize=False).compile(
        'import "a.rif";\n',
        source_name=str(tmp_path / "cycle.rif"),
    )
    assert not cycle.is_success
    assert any("cycle" in item.message.lower() for item in cycle.diagnostics)


def test_imports_reject_traversal_missing_files_and_memory_only_compilation(tmp_path: Path):
    source = 'import "../outside.rif";\n'
    invalid = Compiler(optimize=False).compile(
        source,
        source_name=str(tmp_path / "main.rif"),
    )
    assert not invalid.is_success
    assert any("relative .rif path" in item.message for item in invalid.diagnostics)

    missing = Compiler(optimize=False).compile(
        'import "missing.rif";\n',
        source_name=str(tmp_path / "main.rif"),
    )
    assert not missing.is_success
    assert any("does not exist" in item.message for item in missing.diagnostics)

    memory_only = Compiler(optimize=False).compile('import "module.rif";')
    assert not memory_only.is_success
    assert any("require compiling from a .rif file path" in item.message for item in memory_only.diagnostics)


def test_bytecode_v5_round_trip_and_v4_compatibility():
    source = """struct Point { x: int, y: int }
let point = Point(3, 4);
print(point.x + point.y);
"""
    result = _compile(source)
    restored = BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(result.module))
    assert restored == result.module
    assert VirtualMachine().execute(restored).output == ("7",)

    from rifai.bytecode import CodeChunk, Instruction, Opcode

    legacy_v4 = BytecodeModule(
        constants=(),
        main=CodeChunk(
            name="<main>",
            instructions=(Instruction(Opcode.HALT),),
        ),
        format_version=COLLECTIONS_FORMAT_VERSION,
    )
    encoded = BytecodeSerializer.to_bytes(legacy_v4)
    restored_v4 = BytecodeSerializer.from_bytes(encoded)
    assert restored_v4.format_version == 4
    assert VirtualMachine().execute(restored_v4).output == ()


def test_v5_bytecode_can_be_lifted_to_ir_and_lowered_again():
    source = """enum Status { Ready, Locked }
struct User { name: string, age: int, status: Status }
let user = User("Ada", 36, Status.Ready);
user.age = user.age + abs(-1);
print(user.name);
print(user.age);
print(user.status == Status.Ready);
"""
    compiled = _compile(source)
    lifted = BytecodeToIR().build(compiled.module)
    assert IRVerifier().verify(lifted).is_valid

    lowered = IRToBytecode().lower(lifted)
    assert lowered.format_version == 5
    assert VirtualMachine().execute(lowered).output == ("Ada", "37", "true")


def test_compiler_rejects_nominal_opcodes_in_legacy_bytecode_versions():
    from rifai.bytecode import CodeChunk, Instruction, Opcode

    module = BytecodeModule(
        constants=(),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.ENUM_NEW, "State|Ready,Locked|Ready"),
                Instruction(Opcode.POP),
                Instruction(Opcode.HALT),
            ),
        ),
        format_version=COLLECTIONS_FORMAT_VERSION,
    )
    validation = __import__("rifai.bytecode", fromlist=["BytecodeVerifier"]).BytecodeVerifier().verify(module)
    assert not validation.is_valid
    assert any("requires bytecode version 5" in item.message for item in validation.diagnostics)
