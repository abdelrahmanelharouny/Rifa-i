from __future__ import annotations

import pytest

from rifai.bytecode.codegen import CodeGenerator
from rifai.compiler import Compiler
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.ir import ASTToIR, IRPipeline, IRVerifier
from rifai.vm import VirtualMachine


def _frontend(source: str):
    lexical = Lexer(source).scan_tokens()
    assert not lexical.has_errors, lexical.diagnostics
    parsed = Parser(lexical.tokens).parse()
    assert not parsed.has_errors, parsed.diagnostics
    semantic = SemanticAnalyzer().analyze(parsed.program)
    assert semantic.is_valid, semantic.diagnostics
    return parsed.program, semantic


def test_ast_to_ir_builds_typed_functions_arrays_and_control_flow_directly():
    source = """fn add_bonus(values: int[], bonus: int) -> int {
    if (bonus > 0) { return values[0] + bonus; }
    else { return values[0]; }
}
let scores: int[] = [10, 20];
scores[1] = 25;
push(scores, 30);
let index: int = 0;
let total: int = 0;
while (index < len(scores)) {
    total = total + scores[index];
    index = index + 1;
}
print(add_bonus(scores, 2));
print(total);
"""
    program, semantic = _frontend(source)
    ir = ASTToIR().build(
        program,
        semantic,
        source_name="direct.rif",
        source_text=source,
    )

    assert IRVerifier().verify(ir).is_valid
    assert ir.debug_info is not None
    assert ir.debug_info.source_text == source
    assert {name for name, _ in ir.debug_info.local_symbols} == {"<main>", "add_bonus"}
    assert ir.main.blocks[0].block_id == 0
    assert ir.main.blocks[-1].terminator.__class__.__name__ == "IRHalt"
    assert any(
        block.terminator.__class__.__name__ == "IRBranch"
        for function in (ir.main, *ir.functions)
        for block in function.blocks
    )


def test_direct_ast_ir_pipeline_lowers_and_executes_without_bytecode_lifting():
    source = """fn twice(value: int) -> int { return value * 2; }
let total: int = 0;
while (total < 3) { total = total + 1; }
print(twice(total));
"""
    program, semantic = _frontend(source)
    result = IRPipeline().run_ast(
        program,
        semantic,
        source_name="pipeline.rif",
        source_text=source,
        optimize=False,
    )

    assert result.source_kind == "direct-ast"
    assert IRVerifier().verify(result.ir_module).is_valid
    assert VirtualMachine().execute(result.bytecode_module).output == ("6",)
    assert result.analysis.edge_count > 0
    assert any(item.loop_back_edges for item in result.analysis.functions)


def test_source_compiler_no_longer_calls_legacy_ast_to_bytecode_codegen(monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Compiler.compile must use ASTToIR, not CodeGenerator.generate.")

    monkeypatch.setattr(CodeGenerator, "generate", fail_if_called)
    result = Compiler().compile(
        "let answer: int = 20 + 22; print(answer);",
        source_name="direct-compiler.rif",
    )

    assert result.is_success
    assert result.ir_origin == "direct-ast"
    assert result.ir_module is not None
    assert result.module is not None
    assert result.module.debug_info is not None
    assert result.module.debug_info.source_text == "let answer: int = 20 + 22; print(answer);"
    assert VirtualMachine().execute(result.module).output == ("42",)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """fn is_even(n: int) -> bool {
    if (n == 0) { return true; } else { return is_odd(n - 1); }
}
fn is_odd(n: int) -> bool {
    if (n == 0) { return false; } else { return is_even(n - 1); }
}
print(is_even(8));
print(is_odd(7));
""",
            ("true", "true"),
        ),
        (
            """fn pick(flag: bool) -> int {
    let value: int = 1;
    { let value: int = 2; print(value); }
    if (flag) { value = 4; } else { value = 5; }
    return value;
}
print(pick(true));
print(pick(false));
""",
            ("2", "4", "2", "5"),
        ),
        (
            """fn announce(message: string) -> void {
    print(message);
}
announce("Rifa'i");
""",
            ("Rifa'i",),
        ),
    ],
)
def test_direct_ast_to_ir_preserves_calls_scopes_and_return_behavior(source, expected):
    result = Compiler(optimize=False).compile(source)
    assert result.is_success, result.diagnostics
    assert result.ir_origin == "direct-ast"
    assert IRVerifier().verify(result.ir_module).is_valid
    assert VirtualMachine().execute(result.module).output == expected


def test_compiler_inspection_identifies_direct_ast_ir_origin():
    from rifai.inspect import inspect_source

    snapshot = inspect_source("print(40 + 2);")
    assert snapshot["success"]
    assert snapshot["stages"]["ir"]["origin"] == "direct-ast"
