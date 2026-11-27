from __future__ import annotations

from dataclasses import replace

import pytest

from rifai.bytecode import BytecodeSerializer, BytecodeVerifier
from rifai.compiler import Compiler
from rifai.ir import (
    BytecodeToIR,
    IRAnalyzer,
    IRModule,
    IRPassManager,
    IRToBytecode,
    IRVerifier,
)
from rifai.vm import VirtualMachine


def test_compiler_runs_verified_ir_pipeline_and_exposes_pass_metrics():
    source = """fn square(value: int) -> int {
    return value * value;
}
let total: int = 0;
while (total < 3) {
    total = total + 1;
}
print(square(total));
"""
    result = Compiler().compile(source)

    assert result.is_success
    assert result.ir_module is not None
    assert result.ir_stats is not None
    assert result.ir_analysis is not None
    assert result.ir_stats.passes == (
        "verify-input",
        "ir-constant-propagation",
        "ir-branch-simplification",
        "ir-unreachable-block-elimination",
        "canonical-value-numbering",
        "verify-output",
        "cfg-dominator-analysis",
    )
    assert result.ir_stats.function_count == 2
    assert result.ir_stats.block_count == result.ir_module.block_count
    assert result.ir_stats.operation_count == result.ir_module.operation_count
    assert IRVerifier().verify(result.ir_module).is_valid
    assert VirtualMachine().execute(result.module).output == ("9",)


@pytest.mark.parametrize(
    "source",
    [
        'print("Rifa\'i");',
        """fn add(a: int, b: int) -> int { return a + b; }
print(add(20, 22));""",
        """let values: int[] = [1, 2, 3];
push(values, 4);
print(values[3]);
print(len(values));""",
        """let count: int = 0;
while (count < 2) { count = count + 1; }
if (count == 2) { print("done"); } else { print("bad"); }""",
        """fn choose(flag: bool) -> int {
    if (flag) { return 10; } else { return 20; }
}
print(choose(true));
print(choose(false));""",
    ],
)
def test_ir_roundtrip_preserves_bytecode_and_execution(source):
    compilation = Compiler(optimize=False).compile(source)
    assert compilation.is_success

    ir = BytecodeToIR().build(compilation.module)
    passed = IRPassManager().run(ir, optimize=False)
    restored = IRToBytecode().lower(passed.module)

    assert restored == compilation.module
    assert BytecodeVerifier().verify(restored).is_valid
    assert VirtualMachine().execute(restored).output == VirtualMachine().execute(
        compilation.module
    ).output
    assert BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(restored)) == restored


def test_ir_models_stack_merges_as_explicit_block_parameters():
    source = """fn choose(flag: bool) -> int {
    let result: int = 1;
    if (flag) { result = 2; } else { result = 3; }
    return result;
}
print(choose(true));
"""
    result = Compiler(optimize=False).compile(source)
    assert result.is_success
    ir = result.ir_module
    assert ir is not None
    choose = next(function for function in ir.functions if function.name == "choose")
    assert len(choose.blocks) >= 3
    assert all(isinstance(block.parameters, tuple) for block in choose.blocks)
    assert IRVerifier().verify(ir).is_valid


def test_ir_analysis_finds_loop_back_edges_and_dominators():
    source = """let count: int = 0;
while (count < 3) { count = count + 1; }
print(count);
"""
    result = Compiler(optimize=False).compile(source)
    assert result.is_success
    analysis = IRAnalyzer().analyze(result.ir_module)
    main = next(item for item in analysis.functions if item.name == "<main>")
    assert main.loop_back_edges
    assert dict(main.dominators)[0] == (0,)
    assert analysis.edge_count > 0


def test_ir_verifier_rejects_undefined_virtual_values():
    result = Compiler(optimize=False).compile("print(1);")
    assert result.is_success
    ir = result.ir_module
    block = ir.main.blocks[0]
    operation = block.operations[0]
    malformed_operation = replace(operation, inputs=(999,))
    malformed_block = replace(
        block,
        operations=(malformed_operation, *block.operations[1:]),
    )
    malformed_main = replace(ir.main, blocks=(malformed_block,))
    malformed = replace(ir, main=malformed_main)

    verified = IRVerifier().verify(malformed)
    assert not verified.is_valid
    assert any("undefined" in item for item in verified.diagnostics)


def test_ir_pipeline_is_deterministic_and_value_numbering_is_canonical():
    result = Compiler().compile("let answer: int = (20 + 1) * 2; print(answer);")
    first = IRPassManager().run(BytecodeToIR().build(result.module))
    second = IRPassManager().run(BytecodeToIR().build(result.module))

    assert first.module == second.module
    assert first.analysis == second.analysis
    assert first.stats == second.stats


def test_compiler_exposes_ir_even_when_bytecode_optimization_is_disabled():
    result = Compiler(optimize=False).compile("print(2 + 2);")

    assert result.is_success
    assert result.optimization is None
    assert result.ir_module is not None
    assert result.ir_stats is not None
