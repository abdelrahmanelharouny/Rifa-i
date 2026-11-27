from __future__ import annotations

import pytest

from rifai.compiler import Compiler
from rifai.ir import IRVerifier
from rifai.vm import VMRuntimeError, VirtualMachine


def test_ir_constant_folding_and_constant_branch_pruning():
    source = """print(10 + 32);
if (1 < 2) {
    print(42);
} else {
    print(0);
}
"""
    result = Compiler(optimize=False).compile(source)

    assert result.is_success
    assert result.module is not None
    assert result.ir_module is not None
    assert result.ir_stats is not None
    assert result.ir_stats.constant_folds >= 2
    assert result.ir_stats.branches_simplified == 1
    assert result.ir_stats.blocks_removed >= 1
    assert "ir-constant-propagation" in result.ir_stats.passes
    assert "ir-branch-simplification" in result.ir_stats.passes
    assert IRVerifier().verify(result.ir_module).is_valid
    assert VirtualMachine().execute(result.module).output == ("42", "42")


def test_ir_optimizer_keeps_division_by_zero_as_a_runtime_operation():
    result = Compiler(optimize=False).compile("print(7 / 0);")

    assert result.is_success
    assert result.ir_stats is not None
    assert result.ir_stats.constant_folds == 0
    assert any(
        operation.opcode.value == "DIVIDE"
        for block in result.ir_module.main.blocks
        for operation in block.operations
    )
    with pytest.raises(VMRuntimeError, match="Division by zero"):
        VirtualMachine().execute(result.module)


def test_ir_optimizer_preserves_unknown_runtime_branches_and_loop_back_edges():
    source = """fn choose(flag: bool) -> int {
    if (flag) { return 10; } else { return 20; }
}
let count: int = 0;
while (count < 2) { count = count + 1; }
print(choose(count == 2));
"""
    result = Compiler(optimize=False).compile(source)

    assert result.is_success
    assert result.ir_stats is not None
    assert result.ir_stats.branches_simplified == 0
    assert result.ir_stats.blocks_removed == 0
    assert result.ir_analysis is not None
    assert any(item.loop_back_edges for item in result.ir_analysis.functions)
    assert VirtualMachine().execute(result.module).output == ("10",)
