"""Command-line interface for the Rifa'i compiler and virtual machine."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rifai import __version__
from rifai.bytecode.disassembler import disassemble
from rifai.bytecode.serializer import BytecodeFormatError, BytecodeSerializer
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.compiler import Compiler
from rifai.errors.diagnostics import Diagnostic
from rifai.frontend.ast_nodes import format_ast
from rifai.frontend.lexer import Lexer, LexResult
from rifai.frontend.parser import Parser, ParseResult
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.frontend.tokens import Token
from rifai.vm.machine import VirtualMachine
from rifai.vm.runtime import BytecodeValidationError, VMRuntimeError


def _read_source(file_path: Path) -> str | None:
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[io] {file_path}: {exc.strerror or exc}", file=sys.stderr)
        return None
    except UnicodeDecodeError as exc:
        print(
            f"[io] {file_path}: Failed to decode file as UTF-8 ({exc.reason}).",
            file=sys.stderr,
        )
        return None


def _print_diagnostics(diagnostics: Sequence[Diagnostic], file_path: Path) -> None:
    for diagnostic in diagnostics:
        print(diagnostic.format(str(file_path)), file=sys.stderr)


def _format_token_line(token: Token) -> str:
    location = f"{token.line}:{token.column}"
    literal_part = f"  literal={token.literal!r}" if token.literal is not None else ""
    return (
        f"{location:<10} {token.token_type.name:<15} "
        f"{token.lexeme!r}{literal_part}"
    )


def _run_tokens_command(file_path: Path) -> int:
    source = _read_source(file_path)
    if source is None:
        return 1
    result: LexResult = Lexer(source).scan_tokens()
    for token in result.tokens:
        print(_format_token_line(token))
    if result.has_errors:
        _print_diagnostics(result.diagnostics, file_path)
        return 1
    return 0


def _run_parse_command(file_path: Path) -> int:
    source = _read_source(file_path)
    if source is None:
        return 1
    lex_result = Lexer(source).scan_tokens()
    if lex_result.has_errors:
        _print_diagnostics(lex_result.diagnostics, file_path)
        return 1
    parse_result: ParseResult = Parser(lex_result.tokens).parse()
    if parse_result.has_errors:
        _print_diagnostics(parse_result.diagnostics, file_path)
        return 1
    print(
        f"Parsing succeeded: {len(parse_result.program.declarations)} "
        f"top-level declaration(s)."
    )
    return 0


def _run_ast_command(file_path: Path) -> int:
    source = _read_source(file_path)
    if source is None:
        return 1
    lex_result = Lexer(source).scan_tokens()
    if lex_result.has_errors:
        _print_diagnostics(lex_result.diagnostics, file_path)
        return 1
    parse_result = Parser(lex_result.tokens).parse()
    if parse_result.has_errors:
        _print_diagnostics(parse_result.diagnostics, file_path)
        return 1
    print(format_ast(parse_result.program))
    return 0


def _run_check_command(file_path: Path) -> int:
    source = _read_source(file_path)
    if source is None:
        return 1
    lex_result = Lexer(source).scan_tokens()
    if lex_result.has_errors:
        _print_diagnostics(lex_result.diagnostics, file_path)
        return 1
    parse_result = Parser(lex_result.tokens).parse()
    if parse_result.has_errors:
        _print_diagnostics(parse_result.diagnostics, file_path)
        return 1
    semantic_result = SemanticAnalyzer().analyze(parse_result.program)
    if not semantic_result.is_valid:
        _print_diagnostics(semantic_result.diagnostics, file_path)
        return 1
    print(f"Semantic check passed: {file_path}")
    return 0


def _compile_source_file(file_path: Path, *, optimize: bool = True):
    source = _read_source(file_path)
    if source is None:
        return None, None, None
    result = Compiler(optimize=optimize).compile(source, source_name=str(file_path))
    if not result.is_success:
        _print_diagnostics(result.diagnostics, file_path)
        return None, None, None
    return result.module, result.optimization, result.ir_stats


def _run_compile_command(
    file_path: Path,
    output_path: Path | None,
    *,
    optimize: bool = True,
) -> int:
    if file_path.suffix.lower() != ".rif":
        print(f"[io] Expected a .rif source file, got: {file_path}", file=sys.stderr)
        return 1
    module, stats, ir_stats = _compile_source_file(file_path, optimize=optimize)
    if module is None:
        return 1
    validation = BytecodeVerifier().verify(module)
    if not validation.is_valid:
        _print_diagnostics(validation.diagnostics, file_path)
        return 1
    target = output_path or file_path.with_suffix(".rbc")
    try:
        BytecodeSerializer.write(module, target)
    except (OSError, BytecodeFormatError) as exc:
        print(f"[io] Could not write {target}: {exc}", file=sys.stderr)
        return 1
    print(f"Compilation succeeded: {file_path} -> {target}")
    print(
        f"Bytecode v{module.format_version}: "
        f"{len(module.main.instructions)} main instruction(s), "
        f"{len(module.functions)} function(s), "
        f"{len(module.constants)} constant(s)."
    )
    if stats is not None:
        print(
            f"Optimization: {stats.original_instruction_count} -> "
            f"{stats.optimized_instruction_count} instruction(s), "
            f"{stats.folded_expressions} expression(s) folded, "
            f"{stats.constants_before} -> {stats.constants_after} constant(s)."
        )
        print(
            "Advanced optimization: "
            f"{stats.constant_loads_propagated} constant load(s) propagated, "
            f"{stats.branches_folded} branch(es) folded, "
            f"{stats.unreachable_instructions_removed} unreachable instruction(s) removed, "
            f"{stats.common_subexpressions_eliminated} common expression(s) reused."
        )
    if ir_stats is not None:
        print(
            "IR pipeline: "
            f"{ir_stats.function_count} function(s), "
            f"{ir_stats.block_count} block(s), "
            f"{ir_stats.operation_count} operation(s), "
            f"{ir_stats.value_count} value(s), "
            f"{ir_stats.edge_count} edge(s), "
            f"{ir_stats.loop_back_edge_count} loop back-edge(s), "
            f"{ir_stats.constant_folds} IR constant fold(s), "
            f"{ir_stats.branches_simplified} branch simplification(s), "
            f"{ir_stats.blocks_removed} unreachable block(s) removed."
        )
    return 0


def _load_bytecode(file_path: Path):
    try:
        module = BytecodeSerializer.read(file_path)
    except (OSError, BytecodeFormatError) as exc:
        print(f"[bytecode] {file_path}: {exc}", file=sys.stderr)
        return None
    validation = BytecodeVerifier().verify(module)
    if not validation.is_valid:
        _print_diagnostics(validation.diagnostics, file_path)
        return None
    return module


def _execute_module(module, source_path: Path) -> int:
    try:
        result = VirtualMachine().execute(module)
    except BytecodeValidationError as exc:
        _print_diagnostics(exc.diagnostics, source_path)
        return 1
    except VMRuntimeError as exc:
        print(exc.diagnostic.format(str(source_path)), file=sys.stderr)
        return 1
    for line in result.output:
        print(line)
    return 0


def _run_vm_command(file_path: Path) -> int:
    module = _load_bytecode(file_path)
    if module is None:
        return 1
    return _execute_module(module, file_path)


def _run_command(file_path: Path, *, optimize: bool = True) -> int:
    if file_path.suffix.lower() == ".rbc":
        module = _load_bytecode(file_path)
        if module is None:
            return 1
        return _execute_module(module, file_path)
    if file_path.suffix.lower() != ".rif":
        print(
            f"[io] Expected a .rif source or .rbc bytecode file, got: {file_path}",
            file=sys.stderr,
        )
        return 1
    module, _, _ = _compile_source_file(file_path, optimize=optimize)
    if module is None:
        return 1
    validation = BytecodeVerifier().verify(module)
    if not validation.is_valid:
        _print_diagnostics(validation.diagnostics, file_path)
        return 1
    return _execute_module(module, file_path)


def _run_disasm_command(file_path: Path) -> int:
    module = _load_bytecode(file_path)
    if module is None:
        return 1
    print(disassemble(module))
    return 0


def _run_debug_command(
    file_path: Path,
    breakpoints: Sequence[int],
    *,
    optimize: bool = True,
) -> int:
    """Debug a source program or a standalone compiled bytecode module."""
    debug_source_name = str(file_path)
    if file_path.suffix.lower() == ".rif":
        source = _read_source(file_path)
        if source is None:
            return 1
        result = Compiler(optimize=optimize).compile(source, source_name=str(file_path))
        if not result.is_success or result.module is None:
            _print_diagnostics(result.diagnostics, file_path)
            return 1
        module = result.module
        debug_symbols = module.debug_info.as_mapping() if module.debug_info else result.debug_symbols
        debug_source_name = str(file_path)
    elif file_path.suffix.lower() == ".rbc":
        module = _load_bytecode(file_path)
        if module is None:
            return 1
        info = module.debug_info
        debug_symbols = info.as_mapping() if info is not None else {}
        source = info.source_text if info is not None and info.source_text is not None else ""
        debug_source_name = module.source_name or str(file_path)
        if not source and module.source_name:
            candidate = Path(module.source_name)
            if not candidate.is_absolute() and not candidate.is_file():
                candidate = (file_path.parent / candidate).resolve()
            if candidate.is_file():
                loaded_source = _read_source(candidate)
                if loaded_source is not None:
                    source = loaded_source
                    debug_source_name = str(candidate)
    else:
        print(
            f"[debug] Expected a .rif source or .rbc bytecode file, got: {file_path}",
            file=sys.stderr,
        )
        return 2

    invalid = [line for line in breakpoints if type(line) is not int or line < 1]
    if invalid:
        print("[debug] Breakpoint lines must be positive integers.", file=sys.stderr)
        return 2

    available_lines = {
        instruction.location.line
        for chunk in (module.main, *(function.chunk for function in module.functions))
        for instruction in chunk.instructions
        if instruction.location is not None
    }
    if source:
        out_of_range = [line for line in breakpoints if line > len(source.splitlines())]
        if out_of_range:
            print("[debug] A breakpoint line is outside the source file.", file=sys.stderr)
            return 2
    invalid_lines = [line for line in breakpoints if line not in available_lines]
    if invalid_lines:
        print(
            "[debug] No executable bytecode is mapped to breakpoint line(s): "
            + ", ".join(str(line) for line in invalid_lines),
            file=sys.stderr,
        )
        return 2

    from rifai.vm.debugger import InteractiveDebugger

    debugger = InteractiveDebugger(
        module,
        source,
        debug_symbols=debug_symbols,
        source_name=debug_source_name,
        breakpoints=breakpoints,
    )
    try:
        outcome = debugger.run()
    except VMRuntimeError as exc:
        print(exc.diagnostic.format(debug_source_name), file=sys.stderr)
        return 1
    if outcome.aborted:
        print("Debugging aborted.", file=sys.stderr)
        return 130
    if outcome.execution is None:
        return 1
    print("Program output:")
    for line in outcome.execution.output:
        print(line)
    print(f"Execution finished: {outcome.execution.instructions_executed} instruction(s).")
    return 0


def _run_inspect_command(file_path: Path, output_path: Path | None, *, optimize: bool) -> int:
    source = _read_source(file_path)
    if source is None:
        return 1
    from rifai.inspect import inspect_source
    snapshot = inspect_source(source, source_name=str(file_path), optimize=optimize)
    rendered = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if output_path is None:
        sys.stdout.write(rendered)
    else:
        try:
            output_path.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"[io] Could not write {output_path}: {exc}", file=sys.stderr)
            return 1
    return 0 if snapshot["success"] else 1


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level Rifa'i CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="rifai",
        description="Rifa'i source compiler, bytecode toolchain, and virtual machine.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    source_commands = (
        ("tokens", "Lex a Rifa'i source file and inspect its tokens."),
        ("parse", "Lex and parse a Rifa'i source file."),
        ("ast", "Lex, parse, and print the Rifa'i AST."),
        ("check", "Run lexical, syntax, and semantic validation."),
    )
    for name, help_text in source_commands:
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("file", type=Path, help="Path to a .rif source file.")

    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile a .rif source file into a .rbc bytecode module.",
    )
    compile_parser.add_argument("file", type=Path, help="Path to a .rif source file.")
    compile_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .rbc path (defaults to the source path with a .rbc suffix).",
    )
    compile_parser.add_argument(
        "--no-optimize",
        action="store_true",
        help="Disable both bytecode and IR optimizations for debugging or benchmarking.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Compile and execute a .rif file, or execute an existing .rbc file.",
    )
    run_parser.add_argument(
        "file",
        type=Path,
        help="Path to a .rif source file or .rbc bytecode file.",
    )
    run_parser.add_argument(
        "--no-optimize",
        action="store_true",
        help="Disable bytecode and IR optimization for .rif source files.",
    )

    disasm_parser = subparsers.add_parser(
        "disasm",
        help="Verify and disassemble a compiled Rifa'i .rbc file.",
    )
    disasm_parser.add_argument("file", type=Path, help="Path to a .rbc bytecode file.")

    vm_parser = subparsers.add_parser(
        "vm",
        help="Verify and execute a compiled Rifa'i .rbc file in the Rifa'i VM.",
    )
    vm_parser.add_argument("file", type=Path, help="Path to a .rbc bytecode file.")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Export lexer, AST, semantic, and bytecode pipeline data as JSON.",
    )
    inspect_parser.add_argument("file", type=Path, help="Path to a .rif source file.")
    inspect_parser.add_argument("-o", "--output", type=Path, help="Write JSON to this path instead of stdout.")
    inspect_parser.add_argument("--no-optimize", action="store_true", help="Inspect without bytecode or IR optimization.")

    debug_parser = subparsers.add_parser(
        "debug",
        help="Debug a .rif source program or a compiled .rbc module.",
    )
    debug_parser.add_argument("file", type=Path, help="Path to a .rif source file.")
    debug_parser.add_argument(
        "-b", "--breakpoint", action="append", type=int, default=[],
        help="Pause before executing instructions mapped to this source line; may be repeated.",
    )
    debug_parser.add_argument(
        "--no-optimize", action="store_true",
        help="Disable bytecode and IR optimization to retain the most direct source-level stepping.",
    )

    subparsers.add_parser("debug-adapter", help="Start the Rifa'i Debug Adapter Protocol server over stdio.")
    subparsers.add_parser("lsp", help="Start the Rifa'i Language Server over stdio.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint for the Rifa'i CLI."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "compile":
        return _run_compile_command(
            args.file,
            args.output,
            optimize=not args.no_optimize,
        )
    if args.command == "run":
        return _run_command(args.file, optimize=not args.no_optimize)
    if args.command == "debug":
        return _run_debug_command(
            args.file,
            args.breakpoint,
            optimize=not args.no_optimize,
        )
    if args.command == "inspect":
        if args.file.suffix.lower() != ".rif":
            print(f"[io] Expected a .rif source file, got: {args.file}", file=sys.stderr)
            return 2
        return _run_inspect_command(args.file, args.output, optimize=not args.no_optimize)
    if args.command == "debug-adapter":
        from rifai.vm.dap import serve
        return serve()
    if args.command == "lsp":
        from rifai.lsp import serve
        return serve()

    commands = {
        "tokens": _run_tokens_command,
        "parse": _run_parse_command,
        "ast": _run_ast_command,
        "check": _run_check_command,
        "disasm": _run_disasm_command,
        "vm": _run_vm_command,
    }
    command = commands.get(args.command)
    if command is None:
        parser.print_help()
        return 2
    return command(args.file)
