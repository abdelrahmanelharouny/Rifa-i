# Rifa'i Compiler Architecture

This document describes the modular architecture of the **Rifa'i Compiler** and **Rifa'i VM** across Phase 1 (Lexer) and Phase 2 (Parser, AST, Symbol Table, Semantic Analyzer), and how Phase 3 integrates cleanly.

---

## 1. Pipeline Overview

```text
  [.rif source file]
          │
          ▼
  ┌───────────────────┐
  │  Frontend: Lexer  │  (Phase 1 — Implemented)
  └─────────┬─────────┘
            │  LexResult(tokens, diagnostics)
            ▼
  ┌───────────────────┐
  │  Frontend: Parser │  (Phase 2 — Implemented: Recursive Descent -> AST)
  └─────────┬─────────┘
            │  ParseResult(program, diagnostics)
            ▼
  ┌───────────────────┐
  │ Semantic Analyzer │  (Phase 2 — Implemented: Scopes, Types, Returns)
  └─────────┬─────────┘
            │  SemanticResult(diagnostics, expression_types, bindings)
            ▼
  ┌───────────────────┐
  │ Bytecode Emitter  │  (Phase 3 — Planned: Stack-based .rbc generation)
  └─────────┬─────────┘
            │  BytecodeModule (.rbc)
            ▼
  ┌───────────────────┐
  │     Rifa'i VM     │  (Phase 3 — Planned: Stack VM execution)
  └───────────────────┘
```

---

## 2. Package Layout (`src/rifai/`)

- `rifai/cli.py` & `rifai/__main__.py`: CLI entrypoint (`python -m rifai <command> <file.rif>`) exposing `tokens`, `parse`, `ast`, and `check`.
- `rifai/errors/diagnostics.py`: Unified `Diagnostic` and `DiagnosticPhase` (`LEXER`, `PARSER`, `SEMANTIC`, `BYTECODE`, `VM`, `IO`).
- `rifai/frontend/tokens.py`: `TokenType` enum, `KEYWORDS`, and immutable `Token` dataclass.
- `rifai/frontend/lexer.py`: `Lexer` and `LexResult`.
- `rifai/frontend/ast_nodes.py`: Immutable AST dataclasses (`Program`, statements, expressions, `SourceSpan`) and `format_ast()`.
- `rifai/frontend/parser.py`: Recursive Descent `Parser` and `ParseResult` with panic-mode error recovery.
- `rifai/frontend/types.py`: `RifaiType` enum (`INT`, `FLOAT`, `BOOL`, `STRING`, `VOID`, `ERROR`) and type predicates.
- `rifai/frontend/symbol_table.py`: Nested `Scope`, `VariableSymbol`, `FunctionSymbol`, and `SymbolTable`.
- `rifai/frontend/semantic.py`: `SemanticAnalyzer` and `SemanticResult`.
- `rifai/bytecode/` & `rifai/vm/`: Reserved for Phase 3.

---

## 3. Phase 2 Frontend Components

### 3.1 AST Architecture (`ast_nodes.py`)
- Statements (`Statement`) and expressions (`Expression`) are immutable frozen dataclasses carrying a `SourceSpan` (`line`, `column`, `start_offset`, `end_offset`) and originating operator/identifier `Token`s.
- AST nodes contain no parsing or execution logic.
- `format_ast(node)` produces an indented box-drawing tree for inspection via `python -m rifai ast`.

### 3.2 Recursive Descent Parser (`parser.py`)
- Consumes `LexResult.tokens` without inspecting raw source text.
- Implements layered recursive-descent methods matching `docs/grammar.ebnf` (`_parse_or` -> `_parse_and` -> `_parse_equality` -> `_parse_comparison` -> `_parse_term` -> `_parse_factor` -> `_parse_unary` -> `_parse_primary`).
- Distinguishes top-level `fn` declarations from statements and rejects nested `fn` declarations inside blocks.
- Uses panic-mode synchronization (`_synchronize()`) at `;`, `}`, statement/declaration starters, and `EOF` to accumulate multiple syntax errors without infinite loops.

### 3.3 Symbol Table & Scope Management (`symbol_table.py`)
- `Scope` chains child scopes to their parent (`global` at depth 0, `fn:<name>` at depth 1, nested `block` scopes at depth `N`).
- Supports shadowing in child scopes while rejecting duplicate declarations in the same scope and global name collisions between functions and variables.

### 3.4 Semantic Analyzer & Semantic Model (`semantic.py`)
- **Pass 1**: Collects all top-level `FunctionDeclaration` signatures into global scope, validating parameter uniqueness and forbidding `void` parameter types. This enables recursion, mutual recursion, and forward function calls.
- **Pass 2**: Walks top-level declarations and function bodies in source order (variables are not hoisted), checking strict type compatibility, operator rules, `if`/`while` boolean conditions, `print` non-`void` values, `return` validity, and definite-return coverage for non-`void` functions.
- **Error Suppression**: Uses `RifaiType.ERROR` on invalid subexpressions so a single type mistake does not trigger cascading downstream errors.
- **SemanticResult**: Exposes `diagnostics`, `is_valid`, `global_symbols`, and identity-keyed (`id(node)`) maps `expression_types`, `variable_bindings`, and `function_bindings` (with helpers `type_of`, `variable_for`, `function_for`) so Phase 3 bytecode generation can consume resolved types and symbols without mutating the AST.
