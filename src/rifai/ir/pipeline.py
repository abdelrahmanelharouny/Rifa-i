"""Orchestrate the IR lift, multi-pass pipeline, and bytecode lowering."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.module import BytecodeModule
from rifai.ir.analysis import IRAnalysis
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


class IRPipeline:
    """Verified, deterministic multi-pass IR pipeline for compiler output."""

    def __init__(self) -> None:
        self.builder = BytecodeToIR()
        self.pass_manager = IRPassManager()
        self.lowerer = IRToBytecode()

    def run(self, module: BytecodeModule) -> IRPipelineResult:
        ir_module = self.builder.build(module)
        passes = self.pass_manager.run(ir_module)
        bytecode = self.lowerer.lower(passes.module)
        return IRPipelineResult(
            ir_module=passes.module,
            bytecode_module=bytecode,
            analysis=passes.analysis,
            stats=passes.stats,
        )
