# Rifa'i

**Rifa'i** (`.rif`) is a custom statically typed programming language built from scratch in Python, targeting a custom stack-based bytecode format (`.rbc`) executed by the **Rifa'i VM**.

## Development Status

- **Phase 1 (Complete):** Language specification, formal EBNF grammar, modular compiler architecture, Token system, Lexer with source locations & diagnostics, and `tokens` CLI.
- **Phase 2 (Complete):** Custom AST & tree printer, Recursive Descent Parser with panic-mode recovery, Symbol Table with nested scopes & shadowing, Static Type System, Semantic Analyzer (strict typing, forward references, definite return analysis), and `parse` / `ast` / `check` CLI commands.
- **Phase 3 (Planned):** Stack-based bytecode generator (`.rbc`) and the Rifa'i Virtual Machine.

## CLI Commands

```bash
# Inspect lexical tokens
python -m rifai tokens examples/hello.rif

# Parse syntax
python -m rifai parse examples/hello.rif

# Print formatted AST
python -m rifai ast examples/hello.rif

# Run full frontend validation (Lexer -> Parser -> Semantic Analyzer)
python -m rifai check examples/hello.rif
```

## Setup & Testing

```bash
pip install -e ".[dev]"
python -m pytest -v
```
