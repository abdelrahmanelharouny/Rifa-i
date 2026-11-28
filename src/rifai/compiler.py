"""End-to-end Rifa'i source compilation through the direct IR pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path

from rifai.bytecode.module import BytecodeModule
from rifai.bytecode.optimizer import BytecodeOptimizer, OptimizationStats
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import ImportDeclaration, Program, SourceSpan
from rifai.frontend.tokens import Token
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

    @staticmethod
    def _remap_module_locations(value, line_offset: int, char_offset: int):
        """Translate AST token/spans into the flattened debug source coordinate space."""
        if isinstance(value, Token):
            return replace(
                value,
                line=value.line + line_offset,
                start_offset=value.start_offset + char_offset,
                end_offset=value.end_offset + char_offset,
            )
        if isinstance(value, SourceSpan):
            return replace(
                value,
                line=value.line + line_offset,
                start_offset=value.start_offset + char_offset,
                end_offset=value.end_offset + char_offset,
            )
        if isinstance(value, tuple):
            return tuple(
                Compiler._remap_module_locations(item, line_offset, char_offset)
                for item in value
            )
        if is_dataclass(value):
            return replace(
                value,
                **{
                    item.name: Compiler._remap_module_locations(
                        getattr(value, item.name), line_offset, char_offset
                    )
                    for item in fields(value)
                },
            )
        return value

    def _expand_imports(
        self,
        program: Program,
        source: str,
        source_name: str | None,
    ) -> tuple[Program, str, tuple[Diagnostic, ...]]:
        imports = [
            item for item in program.declarations
            if isinstance(item, ImportDeclaration)
        ]
        if not imports:
            return program, source, ()
        if not source_name or source_name.startswith("<"):
            first = imports[0]
            diagnostic = Diagnostic(
                phase=DiagnosticPhase.PARSER,
                message="Source imports require compiling from a .rif file path.",
                line=first.span.line,
                column=first.span.column,
                start_offset=first.span.start_offset,
                end_offset=first.span.end_offset,
            )
            return program, source, (diagnostic,)

        root_path = Path(source_name).expanduser().resolve()
        root_directory = root_path.parent
        visited: set[Path] = set()
        visiting: set[Path] = set()
        ordered: list[tuple[Path, str, Program]] = []
        diagnostics: list[Diagnostic] = []
        total_chars = 0
        max_modules = 128
        max_source_chars = 5 * 1024 * 1024

        def visit(path: Path, module_source: str, module_program: Program) -> None:
            nonlocal total_chars
            resolved = path.resolve()
            if resolved in visiting:
                diagnostics.append(Diagnostic(
                    phase=DiagnosticPhase.PARSER,
                    message=f"Import cycle detected at '{resolved}'.",
                    line=1,
                    column=1,
                ))
                return
            if resolved in visited:
                return
            if len(visited) + len(visiting) >= max_modules:
                diagnostics.append(Diagnostic(
                    phase=DiagnosticPhase.PARSER,
                    message=f"Module graph exceeds the limit ({max_modules} source files).",
                    line=1,
                    column=1,
                ))
                return
            total_chars += len(module_source)
            if total_chars > max_source_chars:
                diagnostics.append(Diagnostic(
                    phase=DiagnosticPhase.PARSER,
                    message=f"Combined module source exceeds the limit ({max_source_chars} characters).",
                    line=1,
                    column=1,
                ))
                return

            visiting.add(resolved)
            for declaration in module_program.declarations:
                if not isinstance(declaration, ImportDeclaration):
                    continue
                relative = Path(declaration.path)
                if (
                    relative.is_absolute()
                    or not declaration.path
                    or ".." in relative.parts
                    or relative.suffix.lower() != ".rif"
                ):
                    diagnostics.append(Diagnostic(
                        phase=DiagnosticPhase.PARSER,
                        message="Imports must use a relative .rif path without parent-directory segments.",
                        line=declaration.span.line,
                        column=declaration.span.column,
                        start_offset=declaration.span.start_offset,
                        end_offset=declaration.span.end_offset,
                    ))
                    continue
                candidate = (resolved.parent / relative).resolve()
                try:
                    candidate.relative_to(root_directory)
                except ValueError:
                    diagnostics.append(Diagnostic(
                        phase=DiagnosticPhase.PARSER,
                        message=f"Import '{declaration.path}' escapes the root project directory.",
                        line=declaration.span.line,
                        column=declaration.span.column,
                        start_offset=declaration.span.start_offset,
                        end_offset=declaration.span.end_offset,
                    ))
                    continue
                if not candidate.is_file():
                    diagnostics.append(Diagnostic(
                        phase=DiagnosticPhase.PARSER,
                        message=f"Imported source file '{declaration.path}' does not exist.",
                        line=declaration.span.line,
                        column=declaration.span.column,
                        start_offset=declaration.span.start_offset,
                        end_offset=declaration.span.end_offset,
                    ))
                    continue
                try:
                    candidate_size = candidate.stat().st_size
                    if candidate_size > max_source_chars or total_chars + candidate_size > max_source_chars:
                        diagnostics.append(Diagnostic(
                            phase=DiagnosticPhase.PARSER,
                            message=f"Combined module source exceeds the limit ({max_source_chars} characters).",
                            line=declaration.span.line,
                            column=declaration.span.column,
                            start_offset=declaration.span.start_offset,
                            end_offset=declaration.span.end_offset,
                        ))
                        continue
                    imported_source = candidate.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    diagnostics.append(Diagnostic(
                        phase=DiagnosticPhase.PARSER,
                        message=f"Could not read imported module '{candidate}': {exc}.",
                        line=declaration.span.line,
                        column=declaration.span.column,
                    ))
                    continue
                imported_lex = Lexer(imported_source).scan_tokens()
                if imported_lex.has_errors:
                    diagnostics.extend(
                        replace(item, message=f"{candidate}: {item.message}")
                        for item in imported_lex.diagnostics
                    )
                    continue
                imported_parse = Parser(imported_lex.tokens).parse()
                if imported_parse.has_errors:
                    diagnostics.extend(
                        replace(item, message=f"{candidate}: {item.message}")
                        for item in imported_parse.diagnostics
                    )
                    continue
                visit(candidate, imported_source, imported_parse.program)
            visiting.remove(resolved)
            visited.add(resolved)
            ordered.append((resolved, module_source, module_program))

        visit(root_path, source, program)
        if diagnostics:
            return program, source, tuple(diagnostics)

        flattened: list = []
        composite_parts: list[str] = []
        composite_length = 0
        composite_lines = 0
        for path, module_source, module_program in ordered:
            label = f"// module: {path.relative_to(root_directory).as_posix()}\n"
            prefix = label
            line_offset = composite_lines + prefix.count("\n")
            char_offset = composite_length + len(prefix)
            composite_parts.append(prefix)
            composite_parts.append(module_source)
            if not module_source.endswith("\n"):
                composite_parts.append("\n")
            composite_length += len(prefix) + len(module_source) + (
                0 if module_source.endswith("\n") else 1
            )
            composite_lines += prefix.count("\n") + module_source.count("\n") + (
                0 if module_source.endswith("\n") else 1
            )
            for declaration in module_program.declarations:
                if not isinstance(declaration, ImportDeclaration):
                    flattened.append(
                        self._remap_module_locations(
                            declaration, line_offset, char_offset
                        )
                    )
        combined_source = "".join(composite_parts)
        combined_program = replace(
            program,
            declarations=tuple(flattened),
            span=(
                SourceSpan.between(flattened[0].span, flattened[-1].span)
                if flattened
                else program.span
            ),
        )
        return combined_program, combined_source, ()

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

        expanded_program, debug_source, import_diagnostics = self._expand_imports(
            parse_result.program,
            source,
            source_name,
        )
        if import_diagnostics:
            return CompilationResult(None, import_diagnostics)

        semantic_result = SemanticAnalyzer().analyze(expanded_program)
        if not semantic_result.is_valid:
            return CompilationResult(None, semantic_result.diagnostics)

        try:
            ir_result = IRPipeline().run_ast(
                expanded_program,
                semantic_result,
                source_name=source_name,
                source_text=debug_source,
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
