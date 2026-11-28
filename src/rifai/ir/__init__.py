"""Public API for the Rifa'i intermediate representation."""

from rifai.ir.analysis import IRAnalysis, IRAnalyzer, IRFunctionAnalysis
from rifai.ir.advanced_passes import (
    IRCopyPropagationPass,
    IRDeadCodeEliminationPass,
    IRGlobalCommonSubexpressionEliminationPass,
    IRLoopInvariantCodeMotionPass,
)
from rifai.ir.effects import (
    IROperationEffects,
    IRSideEffectAnalysis,
    IRSideEffectSummary,
)
from rifai.ir.ast_to_ir import ASTToIR
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
from rifai.ir.passes import (
    IRBranchSimplificationPass,
    IRConstantPropagationPass,
    IRPassManager,
    IRPassResult,
    IRPassStats,
    IRUnreachableBlockEliminationPass,
    IRValueNumberingPass,
)
from rifai.ir.pipeline import IRPipeline, IRPipelineResult
from rifai.ir.verifier import IRValidationResult, IRVerifier

__all__ = [
    "ASTToIR",
    "IRCopyPropagationPass",
    "IRDeadCodeEliminationPass",
    "IRGlobalCommonSubexpressionEliminationPass",
    "IRLoopInvariantCodeMotionPass",
    "IROperationEffects",
    "IRSideEffectAnalysis",
    "IRSideEffectSummary",
    "BytecodeToIR",
    "IRAnalysis",
    "IRAnalyzer",
    "IRBlock",
    "IRBranch",
    "IRBranchSimplificationPass",
    "IRConstantPropagationPass",
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
    "IRUnreachableBlockEliminationPass",
    "IRValueNumberingPass",
    "IRVerifier",
]
