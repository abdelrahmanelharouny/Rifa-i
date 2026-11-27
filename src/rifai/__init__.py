"""Rifa'i compiler and Virtual Machine package."""

from rifai.bytecode import (
    BytecodeModule,
    BytecodeSerializer,
    BytecodeVerifier,
    CodeChunk,
    Instruction,
    Opcode,
    disassemble,
)
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import Program, format_ast
from rifai.frontend.lexer import Lexer, LexResult
from rifai.frontend.parser import Parser, ParseResult
from rifai.frontend.semantic import SemanticAnalyzer, SemanticResult
from rifai.frontend.tokens import KEYWORDS, Token, TokenType
from rifai.frontend.types import RifaiType
from rifai.vm import ExecutionResult, VirtualMachine, VMRuntimeError

__version__ = "0.3.0"

__all__ = [
    "BytecodeModule",
    "BytecodeSerializer",
    "BytecodeVerifier",
    "CodeChunk",
    "Diagnostic",
    "DiagnosticPhase",
    "ExecutionResult",
    "Instruction",
    "KEYWORDS",
    "LexResult",
    "Lexer",
    "Opcode",
    "ParseResult",
    "Parser",
    "Program",
    "RifaiType",
    "SemanticAnalyzer",
    "SemanticResult",
    "Token",
    "TokenType",
    "VMRuntimeError",
    "VirtualMachine",
    "__version__",
    "disassemble",
    "format_ast",
]
