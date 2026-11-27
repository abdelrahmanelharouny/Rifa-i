import pytest

from rifai.bytecode import (
    BytecodeModule,
    CodeChunk,
    Instruction,
    Opcode,
    SourceLocation,
)
from rifai.bytecode.optimizer import BytecodeOptimizer
from rifai.compiler import Compiler
from rifai.vm import VMRuntimeError, VirtualMachine


def module_for(instructions, constants=()):
    return BytecodeModule(
        constants=tuple(constants),
        main=CodeChunk("<main>", tuple(instructions)),
    )


def test_folds_nested_integer_expressions():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.CONSTANT, 2),
            Instruction(Opcode.MULTIPLY),
            Instruction(Opcode.ADD),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (10, 2, 3),
    )

    result = BytecodeOptimizer().optimize(module)
    assert result.stats.folded_expressions == 2
    assert result.stats.optimized_instruction_count == 3
    assert result.module.constants == (16,)
    assert VirtualMachine().execute(result.module).output == ("16",)


def test_folds_unary_boolean_and_string_expressions():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.NOT),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.CONSTANT, 2),
            Instruction(Opcode.ADD),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (False, "Ri", "fa'i"),
    )
    result = BytecodeOptimizer().optimize(module)
    assert result.stats.folded_expressions == 2
    assert result.module.constants == (True, "Rifa'i")
    assert VirtualMachine().execute(result.module).output == ("true", "Rifa'i")


def test_folds_comparisons_and_logical_operations():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.LESS),
            Instruction(Opcode.CONSTANT, 2),
            Instruction(Opcode.AND),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (2, 5, True),
    )
    result = BytecodeOptimizer().optimize(module)
    assert result.stats.folded_expressions == 2
    assert VirtualMachine().execute(result.module).output == ("true",)


def test_does_not_fold_division_or_modulo_by_zero():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.DIVIDE),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (10, 0),
    )
    result = BytecodeOptimizer().optimize(module)
    assert result.stats.folded_expressions == 0
    with pytest.raises(VMRuntimeError, match="Division by zero"):
        VirtualMachine().execute(result.module)


def test_preserves_source_location_on_folded_instruction():
    location = SourceLocation(3, 12, 20, 23)
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.ADD, location=location),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (2, 5),
    )
    result = BytecodeOptimizer().optimize(module)
    assert result.module.main.instructions[0].location == location


def test_removes_unused_constants_and_keeps_bool_int_types_distinct():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (True, 1, 999),
    )
    result = BytecodeOptimizer().optimize(module)
    assert result.module.constants == (True, 1)
    assert result.stats.constants_before == 3
    assert result.stats.constants_after == 2


def test_removes_stack_neutral_dup_pop_pair():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.DUP),
            Instruction(Opcode.POP),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (7,),
    )
    result = BytecodeOptimizer().optimize(module)
    assert result.stats.removed_noops == 2
    assert result.stats.optimized_instruction_count == 3
    assert VirtualMachine().execute(result.module).output == ("7",)


def test_optimizes_function_chunks_without_changing_function_calls():
    source = """fn answer() -> int {
    return (6 * 7) + 1;
}
print(answer());
"""
    optimized = Compiler(optimize=True).compile(source)
    unoptimized = Compiler(optimize=False).compile(source)
    assert optimized.is_success and unoptimized.is_success
    assert VirtualMachine().execute(optimized.module).output == ("43",)
    assert VirtualMachine().execute(unoptimized.module).output == ("43",)
    assert len(optimized.module.functions[0].chunk.instructions) < len(
        unoptimized.module.functions[0].chunk.instructions
    )


def test_optimizer_is_idempotent():
    compiled = Compiler().compile("print((2 + 3) * 4);")
    first = BytecodeOptimizer().optimize(compiled.module)
    second = BytecodeOptimizer().optimize(first.module)
    assert second.module == first.module
    assert second.stats.folded_expressions == 0


def test_compiler_optimization_preserves_if_and_loop_targets():
    source = """let value: int = 0;
if (true) {
    value = 2 * 3;
} else {
    value = 99;
}
while (value < 7) {
    value = value + 1;
}
print(value);
"""
    optimized = Compiler(optimize=True).compile(source)
    unoptimized = Compiler(optimize=False).compile(source)
    assert optimized.is_success and unoptimized.is_success
    assert VirtualMachine().execute(optimized.module).output == ("7",)
    assert VirtualMachine().execute(unoptimized.module).output == ("7",)


def test_refuses_to_optimize_invalid_bytecode():
    malformed = module_for([Instruction(Opcode.CONSTANT, 20), Instruction(Opcode.HALT)])
    with pytest.raises(ValueError, match="invalid bytecode"):
        BytecodeOptimizer().optimize(malformed)


def test_compacting_expressions_remaps_absolute_jump_targets():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.ADD),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.CONSTANT, 2),
            Instruction(Opcode.JUMP_IF_FALSE, 8),
            Instruction(Opcode.CONSTANT, 3),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (2, 3, False, "unreachable"),
    )
    # Exercise the original peephole compaction in isolation; Phase 10 adds
    # a subsequent CFG-aware pass that intentionally folds this constant branch.
    optimized = BytecodeOptimizer().optimize(module, _advanced=False)

    assert optimized.module.main.instructions[3] == Instruction(
        Opcode.JUMP_IF_FALSE,
        6,
    )
    assert VirtualMachine().execute(optimized.module).output == ("5",)


def test_does_not_fold_when_jump_enters_expression_interior():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.JUMP, 3),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.CONSTANT, 2),
            Instruction(Opcode.ADD),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (99, 4, 5),
    )
    optimized = BytecodeOptimizer().optimize(module)

    assert optimized.stats.folded_expressions == 0
    assert VirtualMachine().execute(optimized.module).output == ("104",)


def test_does_not_remove_dup_pop_pair_when_jump_targets_dup():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.JUMP, 3),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.DUP),
            Instruction(Opcode.POP),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (7, 100),
    )
    optimized = BytecodeOptimizer().optimize(module)

    assert optimized.stats.removed_noops == 0
    assert any(
        instruction.opcode is Opcode.DUP
        for instruction in optimized.module.main.instructions
    )
    assert VirtualMachine().execute(optimized.module).output == ("7",)
