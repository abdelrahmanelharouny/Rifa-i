from __future__ import annotations

from dataclasses import replace

import pytest

from rifai.bytecode import BytecodeVerifier, Opcode
from rifai.compiler import Compiler
from rifai.ir import (
    IRBlock,
    IRCopyPropagationPass,
    IRDeadCodeEliminationPass,
    IRFunction,
    IRGlobalCommonSubexpressionEliminationPass,
    IRHalt,
    IRLoopInvariantCodeMotionPass,
    IRModule,
    IROperation,
    IRPassManager,
    IRReturn,
    IRSideEffectAnalysis,
    IRToBytecode,
    IRValue,
    IRVerifier,
)
from rifai.vm import VMRuntimeError, VirtualMachine


def test_global_cse_reuses_dominating_expressions_across_branches():
    source = """fn calculate(a: int, b: int, flag: bool) -> int {
    let seed: int = a + b;
    if (flag) {
        let answer: int = a + b;
        return answer;
    } else {
        let answer: int = a + b;
        return answer;
    }
}
print(calculate(10, 20, true));
print(calculate(10, 20, false));
"""
    result = Compiler(optimize=False, ir_optimize=True).compile(source)

    assert result.is_success, result.diagnostics
    assert result.ir_stats is not None
    assert result.ir_stats.global_cse_eliminated >= 2
    assert IRVerifier().verify(result.ir_module).is_valid
    assert VirtualMachine().execute(result.module).output == ("30", "30")
    # The first dominating value is reused after control-flow edges, so the
    # lowerer has to materialize virtual values rather than assume a stack-only
    # single-use expression tree.
    assert any(
        instruction.opcode is Opcode.STORE_LOCAL
        for instruction in result.module.functions[0].chunk.instructions
    )


def test_licm_hoists_total_expressions_and_stable_parameter_loads():
    source = """fn count_less(a: int, b: int, limit: int) -> int {
    let index: int = 0;
    let total: int = 0;
    while (index < limit) {
        let condition: bool = a < b;
        if (condition) {
            total = total + 1;
        }
        index = index + 1;
    }
    return total;
}
print(count_less(1, 2, 3));
print(count_less(2, 1, 0));
"""
    result = Compiler(optimize=False, ir_optimize=True).compile(source)

    assert result.is_success, result.diagnostics
    assert result.ir_stats is not None
    assert result.ir_stats.loop_invariants_hoisted >= 3
    assert result.ir_analysis is not None
    assert any(item.loop_back_edges for item in result.ir_analysis.functions)
    assert IRVerifier().verify(result.ir_module).is_valid
    assert VirtualMachine().execute(result.module).output == ("3", "0")


def test_dce_removes_dead_total_operations_but_keeps_faulting_reads():
    main = IRFunction(
        name="<main>",
        blocks=(
            IRBlock(
                block_id=0,
                parameters=(),
                operations=(),
                terminator=IRHalt(),
                source_start=0,
                source_end=0,
                reachable=True,
            ),
        ),
        local_count=0,
        arity=0,
    )
    function = IRFunction(
        name="compare",
        blocks=(
            IRBlock(
                block_id=0,
                parameters=(),
                operations=(
                    IROperation(
                        Opcode.LOAD_LOCAL,
                        (IRValue(0, "int"),),
                        (),
                        operand=0,
                    ),
                    IROperation(
                        Opcode.LOAD_LOCAL,
                        (IRValue(1, "int"),),
                        (),
                        operand=1,
                    ),
                    IROperation(
                        Opcode.EQUAL,
                        (IRValue(2, "bool"),),
                        (0, 1),
                    ),
                ),
                terminator=IRReturn(0),
                source_start=0,
                source_end=0,
                reachable=True,
            ),
        ),
        local_count=2,
        arity=2,
        parameter_types=("int", "int"),
        return_type="int",
    )
    module = IRModule(constants=(), main=main, functions=(function,))
    assert IRVerifier().verify(module).is_valid

    result = IRDeadCodeEliminationPass().run(module)
    optimized_function = result[0].functions[0]
    assert result[1] == 1
    assert [item.opcode for item in optimized_function.blocks[0].operations] == [
        Opcode.LOAD_LOCAL,
        Opcode.LOAD_LOCAL,
    ]
    lowered = IRToBytecode().lower(result[0])
    assert BytecodeVerifier().verify(lowered).is_valid
    assert Opcode.EQUAL not in {
        item.opcode for item in lowered.functions[0].chunk.instructions
    }


def test_copy_propagation_replaces_dup_results_and_preserves_return_value():
    main = IRFunction(
        name="<main>",
        blocks=(
            IRBlock(
                block_id=0,
                parameters=(),
                operations=(
                    IROperation(Opcode.CONSTANT, (IRValue(0, "int"),), (), operand=0),
                    IROperation(Opcode.DUP, (IRValue(1, "int"),), (0,)),
                    IROperation(Opcode.PRINT, (), (1,)),
                ),
                terminator=IRHalt(),
                source_start=0,
                source_end=0,
                reachable=True,
            ),
        ),
        local_count=0,
        arity=0,
    )
    module = IRModule(constants=(42,), main=main)
    propagated, count = IRCopyPropagationPass().run(module)

    assert count == 1
    operations = propagated.main.blocks[0].operations
    assert [item.opcode for item in operations] == [Opcode.CONSTANT, Opcode.PRINT]
    assert operations[-1].inputs == (0,)
    assert IRVerifier().verify(propagated).is_valid
    assert VirtualMachine().execute(IRToBytecode().lower(propagated)).output == ("42",)


def test_global_cse_invalidates_local_loads_after_assignment():
    source = """fn calculate(a: int, b: int) -> int {
    let first: int = a + b;
    a = a + 1;
    let second: int = a + b;
    return first + second;
}
print(calculate(1, 2));
"""
    result = Compiler(optimize=False, ir_optimize=True).compile(source)

    assert result.is_success, result.diagnostics
    assert result.ir_stats is not None
    assert result.ir_stats.global_cse_eliminated >= 0
    assert VirtualMachine().execute(result.module).output == ("7",)


def test_optimizer_preserves_potentially_trapping_unused_operations():
    source = """let values: int[] = [];
pop(values);
print("unreachable");
"""
    result = Compiler(optimize=False, ir_optimize=True).compile(source)

    assert result.is_success, result.diagnostics
    assert result.ir_stats is not None
    assert result.ir_stats.side_effecting_operations >= 1
    with pytest.raises(VMRuntimeError, match="empty array"):
        VirtualMachine().execute(result.module)


def test_side_effect_analysis_classifies_memory_and_observable_operations():
    summary = IRSideEffectAnalysis().analyze(
        Compiler(optimize=False).compile(
            'let values: int[] = [1]; push(values, 2); print(len(values));'
        ).ir_module
    )

    assert summary.operation_count > 0
    assert summary.side_effecting_operations >= 2
    assert summary.memory_writes >= 1
    assert summary.potentially_trapping_operations >= 1


def test_pass_manager_reports_phase14_metrics_and_is_deterministic():
    source = """fn calculate(a: int, b: int, limit: int) -> int {
    let i: int = 0;
    let result: int = 0;
    while (i < limit) {
        let flag: bool = a < b;
        if (flag) { result = result + 1; }
        i = i + 1;
    }
    return result;
}
print(calculate(1, 2, 4));
"""
    first = Compiler(optimize=False, ir_optimize=True).compile(source)
    second = Compiler(optimize=False, ir_optimize=True).compile(source)

    assert first.is_success and second.is_success
    assert first.ir_module == second.ir_module
    assert first.ir_stats == second.ir_stats
    assert first.ir_stats.dead_operations_removed >= 0
    assert first.ir_stats.copy_propagations >= 0
    assert first.ir_stats.global_cse_eliminated >= 0
    assert first.ir_stats.loop_invariants_hoisted >= 0
    assert VirtualMachine().execute(first.module).output == ("4",)
