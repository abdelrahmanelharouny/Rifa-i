"""Command-line interface for the Rifa'i compiler."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rifai import __version__
from rifai.bytecode.disassembler import disassemble
from rifai.bytecode.serializer import BytecodeFormatError, BytecodeSerializer
from rifai.bytecode.verifier import BytecodeVerifier
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


def _run_disasm_command(file_path: Path) -> int:
    module = _load_bytecode(file_path)
    if module is None:
        return 1
    print(disassemble(module))
    return 0


def _run_vm_command(file_path: Path) -> int:
    module = _load_bytecode(file_path)
    if module is None:
        return 1
    try:
        result = VirtualMachine().execute(module)
    except BytecodeValidationError as exc:
        _print_diagnostics(exc.diagnostics, file_path)
        return 1
    except VMRuntimeError as exc:
        print(exc.diagnostic.format(str(file_path)), file=sys.stderr)
        return 1
    for line in result.output:
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level Rifa'i CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="rifai",
        description="Rifa'i programming language compiler and VM CLI.",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint for the Rifa'i CLI."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
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
