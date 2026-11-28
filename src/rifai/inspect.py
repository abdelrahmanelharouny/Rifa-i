"""Structured inspection output for the Rifa'i compiler pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from rifai import __version__
from rifai.bytecode.cfg import analyze_module_control_flow
from rifai.bytecode.disassembler import disassemble
from rifai.compiler import Compiler
from rifai.frontend.ast_nodes import ASTNode
from rifai.frontend.lexer import Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.frontend.tokens import Token


def _walk(node: ASTNode):
    yield node
    for descriptor in fields(node):
        value = getattr(node, descriptor.name)
        if isinstance(value, ASTNode):
            yield from _walk(value)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, ASTNode):
                    yield from _walk(item)


def _safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Token):
        return {
            "type": value.token_type.value,
            "lexeme": value.lexeme,
            "literal": value.literal,
            "line": value.line,
            "column": value.column,
            "start_offset": value.start_offset,
            "end_offset": value.end_offset,
        }
    if isinstance(value, ASTNode):
        return {
            "kind": type(value).__name__,
            **{
                descriptor.name: _safe(getattr(value, descriptor.name))
                for descriptor in fields(value)
            },
        }
    if is_dataclass(value):
        return {descriptor.name: _safe(getattr(value, descriptor.name)) for descriptor in fields(value)}
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _diagnostics(items: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {
            "phase": item.phase.value,
            "message": item.message,
            "line": item.line,
            "column": item.column,
            "start_offset": item.start_offset,
            "end_offset": item.end_offset,
        }
        for item in items
    ]


def _instruction(instruction: Any) -> dict[str, Any]:
    opcode = instruction.opcode.value if isinstance(instruction.opcode, Enum) else str(instruction.opcode)
    location = instruction.location
    return {
        "opcode": opcode,
        "operand": instruction.operand,
        "source": None if location is None else {
            "line": location.line,
            "column": location.column,
        },
    }


def _chunk(chunk: Any) -> dict[str, Any]:
    return {
        "name": chunk.name,
        "arity": chunk.arity,
        "local_count": chunk.local_count,
        "instructions": [_instruction(item) for item in chunk.instructions],
    }


def inspect_source(
    source: str,
    *,
    source_name: str = "<memory>",
    optimize: bool = True,
) -> dict[str, Any]:
    """Run the frontend and compiler and return a JSON-safe pipeline snapshot."""
    result: dict[str, Any] = {
        "schema_version": 1,
        "rifai_version": __version__,
        "source_name": source_name,
        "success": False,
        "stages": {},
        "diagnostics": [],
    }

    lexical = Lexer(source).scan_tokens()
    result["stages"]["lexer"] = {
        "token_count": len(lexical.tokens),
        "tokens": [
            {
                "type": token.token_type.value,
                "lexeme": token.lexeme,
                "literal": token.literal,
                "line": token.line,
                "column": token.column,
                "start_offset": token.start_offset,
                "end_offset": token.end_offset,
            }
            for token in lexical.tokens
        ],
    }
    if lexical.has_errors:
        result["diagnostics"] = _diagnostics(lexical.diagnostics)
        return result

    parsed = Parser(lexical.tokens).parse()
    result["stages"]["parser"] = {
        "success": not parsed.has_errors,
        "declaration_count": len(parsed.program.declarations),
        "ast": _safe(parsed.program),
    }
    if parsed.has_errors:
        result["diagnostics"] = _diagnostics(parsed.diagnostics)
        return result

    semantic = SemanticAnalyzer().analyze(parsed.program)
    expression_types = []
    for node in _walk(parsed.program):
        if hasattr(node, "span"):
            rifai_type = semantic.expression_types.get(id(node))
            if rifai_type is not None:
                expression_types.append({
                    "node": type(node).__name__,
                    "type": rifai_type.value,
                    "line": node.span.line,
                    "column": node.span.column,
                    "start_offset": node.span.start_offset,
                    "end_offset": node.span.end_offset,
                })
    symbols = []
    for name, symbol in sorted(semantic.global_symbols.items()):
        if hasattr(symbol, "params"):
            signature = {
                "parameters": [
                    {"name": param.name, "type": param.rifai_type.value}
                    for param in symbol.params
                ],
                "return_type": symbol.return_type.value,
            }
            kind = "function"
        else:
            signature = {"type": symbol.rifai_type.value, "global": symbol.is_global}
            kind = "variable"
        symbols.append({"name": name, "kind": kind, **signature})
    result["stages"]["semantic"] = {
        "success": semantic.is_valid,
        "global_symbols": symbols,
        "expression_types": expression_types,
    }
    if not semantic.is_valid:
        result["diagnostics"] = _diagnostics(semantic.diagnostics)
        return result

    compilation = Compiler(optimize=optimize).compile(source, source_name=source_name)
    if not compilation.is_success or compilation.module is None:
        result["diagnostics"] = _diagnostics(compilation.diagnostics)
        return result

    module = compilation.module
    result["stages"]["bytecode"] = {
        "format_version": module.format_version,
        "constants": [
            {"index": index, "type": type(value).__name__, "value": value}
            for index, value in enumerate(module.constants)
        ],
        "main": _chunk(module.main),
        "functions": [
            {
                "name": function.name,
                "parameter_types": list(function.parameter_types),
                "return_type": function.return_type,
                "chunk": _chunk(function.chunk),
            }
            for function in module.functions
        ],
        "disassembly": disassemble(module),
        "optimization": _safe(compilation.optimization),
        "control_flow": {
            name: graph.as_dict()
            for name, graph in analyze_module_control_flow(module).items()
        },
    }
    if compilation.ir_module is not None:
        result["stages"]["ir"] = compilation.ir_module.as_dict()
        result["stages"]["ir"]["origin"] = compilation.ir_origin
    if compilation.ir_stats is not None:
        result["stages"]["ir_pipeline"] = _safe(compilation.ir_stats)
    if compilation.ir_analysis is not None:
        result["stages"]["ir_analysis"] = compilation.ir_analysis.as_dict()
    result["success"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rifai inspect",
        description="Export a structured JSON snapshot of the Rifa'i compiler pipeline.",
    )
    parser.add_argument("file", type=Path, help="Path to a .rif source file.")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON to this path instead of stdout.")
    parser.add_argument("--no-optimize", action="store_true", help="Inspect unoptimized bytecode.")
    args = parser.parse_args(argv)

    if args.file.suffix.lower() != ".rif":
        print(f"Expected a .rif source file, got: {args.file}", file=sys.stderr)
        return 2
    try:
        source = args.file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Could not read {args.file}: {exc}", file=sys.stderr)
        return 1

    snapshot = inspect_source(
        source,
        source_name=str(args.file),
        optimize=not args.no_optimize,
    )
    rendered = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"Could not write {args.output}: {exc}", file=sys.stderr)
            return 1
    return 0 if snapshot["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
