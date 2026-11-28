"""End-to-end Rifa'i source compilation through the direct IR pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from rifai.bytecode.module import BytecodeModule
from rifai.bytecode.optimizer import BytecodeOptimizer, OptimizationStats
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.ir.analysis import IRAnalysis
from rifai.ir.model import IRModule
from rifai.ir.pipeline import IRPipeline
from rifai.ir.passes import IRPassStats


@dataclass(frozen=True, slots=True)
class CompilationResult:
    """Result of running the Rifa'i frontend, direct IR pipeline, and backend."""

    module: BytecodeModule | None
    diagnostics: tuple[Diagnostic, ...]
    optimization: OptimizationStats | None = None
    debug_symbols: dict[str, dict[int, tuple[str, str]]] = field(default_factory=dict)
    ir_module: IRModule | None = None
    ir_stats: IRPassStats | None = None
    ir_analysis: IRAnalysis | None = None
    ir_origin: str = "direct-ast"

    @property
    def is_success(self) -> bool:
        """Return True when verified bytecode was successfully produced."""
        return self.module is not None and not self.diagnostics


class Compiler:
    """Compile Rifa'i source text through AST -> IR -> verified bytecode.

    The source compiler now creates IR directly from the semantically-bound AST.
    Compiler(optimize=False) disables both IR and target-bytecode optimizations
    while preserving verification and analysis. Set ir_optimize=True to
    explicitly enable the IR pass manager while leaving backend optimization off.
    """

    def __init__(
        self,
        *,
        optimize: bool = True,
        ir_optimize: bool | None = None,
    ) -> None:
        self.optimize = optimize
        self.ir_optimize = optimize if ir_optimize is None else ir_optimize

    def compile(
        self,
        source: str,
        *,
        source_name: str | None = None,
    ) -> CompilationResult:
        lex_result = Lexer(source).scan_tokens()
        if lex_result.has_errors:
            return CompilationResult(None, lex_result.diagnostics)

        parse_result = Parser(lex_result.tokens).parse()
        if parse_result.has_errors:
            return CompilationResult(None, parse_result.diagnostics)

        semantic_result = SemanticAnalyzer().analyze(parse_result.program)
        if not semantic_result.is_valid:
            return CompilationResult(None, semantic_result.diagnostics)

        try:
            ir_result = IRPipeline().run_ast(
                parse_result.program,
                semantic_result,
                source_name=source_name,
                source_text=source,
                optimize=self.ir_optimize,
            )
        except (TypeError, ValueError, RuntimeError, KeyError, IndexError) as exc:
            diagnostic = Diagnostic(
                phase=DiagnosticPhase.BYTECODE,
                message=f"Direct AST-to-IR compilation failed: {exc}",
                line=1,
                column=1,
            )
            return CompilationResult(None, (diagnostic,), ir_origin="direct-ast")

        module = ir_result.bytecode_module
        optimization: OptimizationStats | None = None

        # Keep the stack-machine cleanup pass as a backend-specific stage. All
        # language-level lowering and data-flow optimizations now happen in IR.
        if self.optimize:
            optimized = BytecodeOptimizer().optimize(module)
            module = optimized.module
            optimization = optimized.stats

        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            return CompilationResult(
                None,
                validation.diagnostics,
                optimization,
                ir_module=ir_result.ir_module,
                ir_stats=ir_result.stats,
                ir_analysis=ir_result.analysis,
                ir_origin=ir_result.source_kind,
            )

        symbols = module.debug_info.as_mapping() if module.debug_info else {}
        return CompilationResult(
            module=module,
            diagnostics=(),
            optimization=optimization,
            debug_symbols=symbols,
            ir_module=ir_result.ir_module,
            ir_stats=ir_result.stats,
            ir_analysis=ir_result.analysis,
            ir_origin=ir_result.source_kind,
        )
