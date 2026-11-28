from __future__ import annotations

from rifai.bytecode import (
    BytecodeDebugInfo,
    BytecodeDebugLocal,
    BytecodeModule,
    BytecodeSerializer,
    BytecodeVerifier,
    CodeChunk,
    FUNCTIONS_FORMAT_VERSION,
    Instruction,
    Opcode,
)
from rifai.compiler import Compiler
from rifai.vm.machine import VirtualMachine


SOURCE = """fn add(a: int, b: int) -> int {
    let result: int = a + b;
    return result;
}
let answer: int = add(20, 22);
print(answer);
"""


def test_compiler_embeds_source_and_local_symbols_and_rbc_round_trips() -> None:
    compiled = Compiler().compile(SOURCE, source_name="embedded.rif")
    assert compiled.is_success and compiled.module is not None
    module = compiled.module

    assert module.format_version == 5
    assert module.debug_info is not None
    assert module.debug_info.source_text == SOURCE
    symbols = module.debug_info.as_mapping()
    assert symbols["add"][0] == ("a", "int")
    assert symbols["add"][1] == ("b", "int")
    assert ("result", "int") in symbols["add"].values()
    # Top-level declarations are globals, not local slots in the main frame.
    assert symbols["<main>"] == {}

    restored = BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(module))
    assert restored == module
    snapshots = []
    execution = VirtualMachine().execute(
        restored,
        on_instruction=snapshots.append,
        debug_symbols=restored.debug_info.as_mapping(),
    )
    assert execution.output == ("42",)
    assert any(
        ("answer", 42) in snapshot.globals
        for snapshot in snapshots
    )


def test_optimizer_preserves_embedded_debug_metadata() -> None:
    compiled = Compiler(optimize=True).compile(SOURCE, source_name="optimized.rif")
    assert compiled.is_success and compiled.module is not None
    assert compiled.module.debug_info is not None
    assert compiled.module.debug_info.source_text == SOURCE
    assert compiled.module.debug_info.as_mapping()["add"][0] == ("a", "int")


def test_version_two_modules_remain_readable_and_writable() -> None:
    module = BytecodeModule(
        constants=(42,),
        main=CodeChunk(
            "<main>",
            (
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
        format_version=FUNCTIONS_FORMAT_VERSION,
    )
    restored = BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(module))
    assert restored == module
    assert restored.debug_info is None
    assert VirtualMachine().execute(restored).output == ("42",)
    assert BytecodeVerifier().verify(restored).is_valid


def test_legacy_format_cannot_silently_drop_debug_metadata() -> None:
    module = BytecodeModule(
        constants=(),
        main=CodeChunk("<main>", (Instruction(Opcode.HALT),)),
        format_version=FUNCTIONS_FORMAT_VERSION,
        debug_info=BytecodeDebugInfo(source_text=""),
    )
    try:
        BytecodeSerializer.to_bytes(module)
    except ValueError as exc:
        assert "requires bytecode version 3" in str(exc)
    else:
        raise AssertionError("Expected old bytecode version to reject debug metadata")


def test_verifier_rejects_debug_symbols_that_reference_nonexistent_slots() -> None:
    module = BytecodeModule(
        constants=(),
        main=CodeChunk("<main>", (Instruction(Opcode.HALT),), local_count=0),
        debug_info=BytecodeDebugInfo(
            source_text="",
            local_symbols=(
                ("<main>", (BytecodeDebugLocal(3, "missing", "int"),)),
            ),
        ),
    )
    result = BytecodeVerifier().verify(module)
    assert not result.is_valid
    assert any("Debug local slot" in item.message for item in result.diagnostics)
