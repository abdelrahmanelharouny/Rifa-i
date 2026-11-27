from __future__ import annotations

import pytest

from rifai.bytecode import (
    BytecodeFunction,
    BytecodeModule,
    BytecodeSerializer,
    BytecodeVerifier,
    CodeChunk,
    Instruction,
    Opcode,
)
from rifai.compiler import Compiler
from rifai.vm import InteractiveDebugger, VMRuntimeError, VirtualMachine


def _run(source: str) -> tuple[str, ...]:
    compiled = Compiler().compile(source, source_name="arrays.rif")
    assert compiled.is_success, [item.message for item in compiled.diagnostics]
    assert compiled.module is not None
    return VirtualMachine().execute(compiled.module).output


def test_array_literals_indexing_assignment_and_standard_library() -> None:
    output = _run(
        """
        let values: int[] = [1, 2, 3];
        print(len(values));
        print(values[1]);
        values[1] = 9;
        push(values, 4);
        print(pop(values));
        print(len(values));
        print(values[1]);
        """
    )
    assert output == ("3", "2", "4", "3", "9")


def test_empty_arrays_require_and_use_the_declared_type() -> None:
    output = _run(
        """
        let names: string[] = [];
        print(len(names));
        push(names, "Rifa'i");
        print(names[0]);
        """
    )
    assert output == ("0", "Rifa'i")


def test_typed_arrays_can_cross_function_boundaries_and_be_returned() -> None:
    output = _run(
        """
        fn sum(values: int[]) -> int {
            let result: int = 0;
            let index: int = 0;
            while (index < len(values)) {
                result = result + values[index];
                index = index + 1;
            }
            return result;
        }

        fn make_words() -> string[] {
            return ["typed", "collections"];
        }

        let numbers: int[] = [2, 3, 5, 7];
        let words: string[] = make_words();
        print(sum(numbers));
        print(words[1]);
        """
    )
    assert output == ("17", "collections")


def test_arrays_are_reference_values_and_alias_mutations_are_visible() -> None:
    output = _run(
        """
        let first: int[] = [4, 5];
        let alias: int[] = first;
        alias[0] = 99;
        push(alias, 8);
        print(first[0]);
        print(len(first));
        """
    )
    assert output == ("99", "3")


@pytest.mark.parametrize(
    "source, expected",
    [
        ('let values: int[] = [1, "two"];', "Array elements must all have type 'int'"),
        ('let values: int[] = [1]; values[0] = "wrong";', "Array element expects 'int'"),
        ("let values: int[] = [1]; push(values, true);", "'push' expects an element of type 'int'"),
        ("let size: int = len(10);", "'len' expects a string or array"),
        ('let value: int = pop("text");', "'pop' expects an array"),
        ("let values: int[] = [[1], [2]];", "Arrays can contain only primitive"),
    ],
)
def test_array_types_and_builtins_are_checked_statically(source: str, expected: str) -> None:
    result = Compiler().compile(source)
    assert not result.is_success
    assert any(expected in item.message for item in result.diagnostics)


def test_empty_array_without_context_is_rejected() -> None:
    result = Compiler().compile("print(len([]));")
    assert not result.is_success
    assert any(
        "empty array literal requires an explicit array type" in item.message
        for item in result.diagnostics
    )


@pytest.mark.parametrize(
    "source, message",
    [
        ("let values: int[] = [1]; print(values[1]);", "out of bounds"),
        ("let values: int[] = [1]; values[-1] = 2;", "out of bounds"),
        ("let values: int[] = []; pop(values);", "empty array"),
    ],
)
def test_invalid_array_runtime_accesses_raise_source_aware_errors(source: str, message: str) -> None:
    compiled = Compiler().compile(source, source_name="bounds.rif")
    assert compiled.is_success and compiled.module is not None
    with pytest.raises(VMRuntimeError, match=message):
        VirtualMachine().execute(compiled.module)


def test_array_capacity_is_enforced_for_literal_and_push() -> None:
    compiled = Compiler().compile(
        "let values: int[] = [1, 2]; push(values, 3);"
    )
    assert compiled.is_success and compiled.module is not None
    with pytest.raises(VMRuntimeError, match="Array item limit"):
        VirtualMachine(max_array_items=2).execute(compiled.module)


def test_vm_rejects_runtime_array_type_mismatch_in_untrusted_bytecode() -> None:
    function = BytecodeFunction(
        name="needs_strings",
        chunk=CodeChunk(
            "needs_strings",
            (Instruction(Opcode.LOAD_LOCAL, 0), Instruction(Opcode.RETURN)),
            local_count=1,
            arity=1,
        ),
        parameter_types=("string[]",),
        return_type="string[]",
    )
    module = BytecodeModule(
        constants=(1,),
        main=CodeChunk(
            "<main>",
            (
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.ARRAY_NEW_INT, 1),
                Instruction(Opcode.CALL, "needs_strings"),
                Instruction(Opcode.POP),
                Instruction(Opcode.HALT),
            ),
        ),
        functions=(function,),
    )
    with pytest.raises(VMRuntimeError, match="expected 'string\[\]'"):
        VirtualMachine().execute(module)


def test_bytecode_v4_array_operations_round_trip_and_run() -> None:
    compiled = Compiler().compile("let xs: int[] = [6, 7]; print(xs[1]);")
    assert compiled.is_success and compiled.module is not None
    assert compiled.module.format_version == 4

    encoded = BytecodeSerializer.to_bytes(compiled.module)
    restored = BytecodeSerializer.from_bytes(encoded)
    assert restored == compiled.module
    assert BytecodeVerifier().verify(restored).is_valid
    assert VirtualMachine().execute(restored).output == ("7",)


def test_array_opcodes_are_rejected_in_bytecode_v3() -> None:
    from dataclasses import replace

    module = BytecodeModule(
        constants=(7,),
        main=CodeChunk(
            "<main>",
            (
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.ARRAY_NEW_INT, 1),
                Instruction(Opcode.LENGTH),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
    )
    old_version = replace(module, format_version=3)
    result = BytecodeVerifier().verify(old_version)
    assert not result.is_valid
    assert any("requires bytecode version 4" in item.message for item in result.diagnostics)



@pytest.mark.parametrize("parameter_name", ["len", "push", "pop"])
def test_builtin_names_are_reserved_for_function_parameters(parameter_name: str) -> None:
    result = Compiler().compile(
        f"fn invalid({parameter_name}: int) -> int {{ return {parameter_name}; }}"
    )
    assert not result.is_success
    assert any("reserved standard-library function name" in item.message for item in result.diagnostics)


def test_initial_global_arrays_obey_nested_value_resource_limits() -> None:
    from rifai.vm import ArrayValue

    module = Compiler().compile("let values: int[] = []; print(len(values));").module
    assert module is not None
    with pytest.raises(ValueError, match="bounded homogeneous array"):
        VirtualMachine(max_integer_bits=8).execute(
            module,
            initial_globals={"values": ArrayValue("int", [1 << 40])},
        )
    with pytest.raises(ValueError, match="bounded homogeneous array"):
        VirtualMachine(max_string_length=2).execute(
            module,
            initial_globals={"values": ArrayValue("string", ["long"])},
        )


def test_v3_debug_metadata_remains_readable_and_executable() -> None:
    from dataclasses import replace

    compiled = Compiler().compile('print("legacy debug");', source_name="v3.rif")
    assert compiled.is_success and compiled.module is not None
    v3 = replace(compiled.module, format_version=3)
    decoded = BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(v3))
    assert decoded.format_version == 3
    assert decoded.debug_info == v3.debug_info
    assert VirtualMachine().execute(decoded).output == ("legacy debug",)


def test_function_array_signatures_are_rejected_before_bytecode_v4() -> None:
    from dataclasses import replace

    compiled = Compiler().compile(
        "fn identity(values: int[]) -> int[] { return values; }"
    )
    assert compiled.is_success and compiled.module is not None
    legacy = replace(compiled.module, format_version=3)
    result = BytecodeVerifier().verify(legacy)
    assert not result.is_valid
    assert any(
        "array parameters require bytecode version 4" in item.message
        for item in result.diagnostics
    )


def test_cli_debugger_displays_array_locals_with_source_names() -> None:
    source = """fn inspect() {
    let values: int[] = [4, 5];
    print(values[0]);
}
inspect();
"""
    compiled = Compiler().compile(source, source_name="arrays.rif")
    assert compiled.is_success and compiled.module is not None
    commands = iter(["continue", "locals", "continue"])
    output: list[str] = []
    debugger = InteractiveDebugger(
        compiled.module,
        source,
        debug_symbols=compiled.module.debug_info.as_mapping(),
        source_name="arrays.rif",
        breakpoints=[3],
        input_fn=lambda _: next(commands),
        output_fn=output.append,
    )
    result = debugger.run()
    assert not result.aborted
    rendered = "\n".join(output)
    assert "values: int[] = [4, 5]" in rendered
