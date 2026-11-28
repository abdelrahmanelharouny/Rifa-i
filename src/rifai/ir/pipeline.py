"""Orchestrate direct or compatibility IR construction, passes, and lowering."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.module import BytecodeModule
from rifai.frontend.ast_nodes import Program
from rifai.frontend.semantic import SemanticResult
from rifai.ir.analysis import IRAnalysis
from rifai.ir.ast_to_ir import ASTToIR
from rifai.ir.builder import BytecodeToIR
from rifai.ir.lower import IRToBytecode
from rifai.ir.model import IRModule
from rifai.ir.passes import IRPassManager, IRPassStats


@dataclass(frozen=True, slots=True)
class IRPipelineResult:
    ir_module: IRModule
    bytecode_module: BytecodeModule
    analysis: IRAnalysis
    stats: IRPassStats
    source_kind: str = "bytecode-lift"


class IRPipeline:
    """Verified, deterministic IR pipeline with a direct source frontend."""

    def __init__(self) -> None:
        self.ast_builder = ASTToIR()
        self.bytecode_builder = BytecodeToIR()
        self.pass_manager = IRPassManager()
        self.lowerer = IRToBytecode()

    def _finish(
        self,
        ir_module: IRModule,
        *,
        optimize: bool,
        source_kind: str,
    ) -> IRPipelineResult:
        passes = self.pass_manager.run(ir_module, optimize=optimize)
        bytecode = self.lowerer.lower(passes.module)
        return IRPipelineResult(
            ir_module=passes.module,
            bytecode_module=bytecode,
            analysis=passes.analysis,
            stats=passes.stats,
            source_kind=source_kind,
        )

    def run_ast(
        self,
        program: Program,
        semantic: SemanticResult,
        *,
        source_name: str | None = None,
        source_text: str | None = None,
        optimize: bool = True,
    ) -> IRPipelineResult:
        """Compile a semantic AST directly into IR, then verify, pass, and lower."""
        module = self.ast_builder.build(
            program,
            semantic,
            source_name=source_name,
            source_text=source_text,
        )
        return self._finish(
            module,
            optimize=optimize,
            source_kind="direct-ast",
        )

    def run(self, module: BytecodeModule, *, optimize: bool = True) -> IRPipelineResult:
        """Compatibility entry point for lifting an existing bytecode module."""
        ir_module = self.bytecode_builder.build(module)
        return self._finish(
            ir_module,
            optimize=optimize,
            source_kind="bytecode-lift",
        )
