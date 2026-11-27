"""End-to-end Rifa'i source compilation pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.codegen import CodeGenerator
from rifai.bytecode.module import BytecodeModule
from rifai.bytecode.optimizer import BytecodeOptimizer, OptimizationStats
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.errors.diagnostics import Diagnostic
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer


@dataclass(frozen=True, slots=True)
class CompilationResult:
    """Result of running every frontend and bytecode-generation phase."""

    module: BytecodeModule | None
    diagnostics: tuple[Diagnostic, ...]
    optimization: OptimizationStats | None = None

    @property
    def is_success(self) -> bool:
        return self.module is not None and not self.diagnostics


class Compiler:
    """Compile Rifa'i source text into verified bytecode.

    Optimization is enabled by default. Use Compiler(optimize=False) to obtain
    the direct code-generator output for debugging and performance comparisons.
    """

    def __init__(self, *, optimize: bool = True) -> None:
        self.optimize = optimize

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

        generation = CodeGenerator().generate(
            parse_result.program,
            semantic_result,
            source_name=source_name,
        )
        if not generation.is_success or generation.module is None:
            return CompilationResult(None, generation.diagnostics)

        module = generation.module
        optimization: OptimizationStats | None = None
        if self.optimize:
            optimized = BytecodeOptimizer().optimize(module)
            module = optimized.module
            optimization = optimized.stats

        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            return CompilationResult(None, validation.diagnostics, optimization)
        return CompilationResult(module, (), optimization)
