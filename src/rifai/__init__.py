"""Rifa'i compiler and Virtual Machine package."""

from rifai.bytecode import (
    BytecodeDebugInfo,
    BytecodeDebugLocal,
    BytecodeFunction,
    BytecodeModule,
    BytecodeOptimizer,
    BytecodeSerializer,
    BytecodeVerifier,
    CodeChunk,
    CodeGenerator,
    Instruction,
    Opcode,
    OptimizationResult,
    OptimizationStats,
    disassemble,
)
from rifai.compiler import CompilationResult, Compiler
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import Program, format_ast
from rifai.frontend.lexer import Lexer, LexResult
from rifai.frontend.parser import Parser, ParseResult
from rifai.frontend.semantic import SemanticAnalyzer, SemanticResult
from rifai.frontend.tokens import KEYWORDS, Token, TokenType
from rifai.frontend.types import RifaiType
from rifai.vm import (
    DebugFrameSnapshot,
    DebugLocalSnapshot,
    DebuggerResult,
    ExecutionResult,
    InstructionSnapshot,
    InteractiveDebugger,
    VirtualMachine,
    VMRuntimeError,
)

__version__ = "0.8.0"

__all__ = [
    "BytecodeDebugInfo",
    "BytecodeDebugLocal",
    "BytecodeFunction",
    "BytecodeModule",
    "BytecodeOptimizer",
    "BytecodeSerializer",
    "BytecodeVerifier",
    "CodeChunk",
    "CodeGenerator",
    "CompilationResult",
    "Compiler",
    "Diagnostic",
    "DiagnosticPhase",
    "DebugFrameSnapshot",
    "DebugLocalSnapshot",
    "DebuggerResult",
    "ExecutionResult",
    "Instruction",
    "InstructionSnapshot",
    "InteractiveDebugger",
    "KEYWORDS",
    "LexResult",
    "Lexer",
    "Opcode",
    "OptimizationResult",
    "OptimizationStats",
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
