"""Public API for the Rifa'i intermediate representation."""

from rifai.ir.analysis import IRAnalysis, IRAnalyzer, IRFunctionAnalysis
from rifai.ir.builder import BytecodeToIR
from rifai.ir.lower import IRToBytecode
from rifai.ir.model import (
    IRBlock,
    IRBranch,
    IRFunction,
    IRHalt,
    IRJump,
    IRLocal,
    IRModule,
    IROperation,
    IRReturn,
    IRValue,
)
from rifai.ir.passes import IRPassManager, IRPassResult, IRPassStats, IRValueNumberingPass
from rifai.ir.pipeline import IRPipeline, IRPipelineResult
from rifai.ir.verifier import IRValidationResult, IRVerifier

__all__ = [
    "BytecodeToIR",
    "IRAnalysis",
    "IRAnalyzer",
    "IRBlock",
    "IRBranch",
    "IRFunction",
    "IRFunctionAnalysis",
    "IRHalt",
    "IRJump",
    "IRLocal",
    "IRModule",
    "IROperation",
    "IRPassManager",
    "IRPassResult",
    "IRPassStats",
    "IRPipeline",
    "IRPipelineResult",
    "IRReturn",
    "IRToBytecode",
    "IRValidationResult",
    "IRValue",
    "IRValueNumberingPass",
    "IRVerifier",
]
