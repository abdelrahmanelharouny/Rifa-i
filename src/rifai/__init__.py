"""Rifa'i compiler and Virtual Machine package."""

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import Program, format_ast
from rifai.frontend.lexer import Lexer, LexResult
from rifai.frontend.parser import Parser, ParseResult
from rifai.frontend.semantic import SemanticAnalyzer, SemanticResult
from rifai.frontend.tokens import KEYWORDS, Token, TokenType
from rifai.frontend.types import RifaiType

__version__ = "0.2.0"

__all__ = [
    "Diagnostic",
    "DiagnosticPhase",
    "KEYWORDS",
    "LexResult",
    "Lexer",
    "ParseResult",
    "Parser",
    "Program",
    "RifaiType",
    "SemanticAnalyzer",
    "SemanticResult",
    "Token",
    "TokenType",
    "__version__",
    "format_ast",
]
