# Rifa'i

**Rifa'i** (.rif) is a custom statically typed programming language built from scratch in Python. Its target is a versioned custom stack-based bytecode format (.rbc), executed by the **Rifa'i VM**.

## Development Status

- **Phase 1 (Complete):** Language specification, formal EBNF grammar, modular compiler architecture, Token system, Lexer with source locations and diagnostics, and the tokens CLI.
- **Phase 2 (Complete):** Custom AST and tree printer, Recursive Descent Parser with panic-mode recovery, nested Symbol Table, static Type System, Semantic Analyzer (strict typing, forward references, definite-return analysis), and parse / ast / check CLI commands.
- **Phase 3 (Complete):** Versioned .rbc module format, typed constant pool, stack-based instruction set, bytecode verifier, deterministic serializer, disassembler, and executable Rifa'i VM core with stack, local/global storage, arithmetic, comparisons, logical operations, jumps, output capture, and runtime diagnostics.
- **Phase 4 (Planned):** AST-to-bytecode Code Generation, source-level control-flow compilation, functions, call frames, and full source-to-bytecode execution.
- **Phase 5 (Planned):** Compiler optimizations, expanded verification, end-to-end hardening, complete documentation, and final delivery.

## CLI Commands

~~~bash
# Frontend inspection and validation
python -m rifai tokens examples/hello.rif
python -m rifai parse examples/hello.rif
python -m rifai ast examples/hello.rif
python -m rifai check examples/hello.rif

# Inspect or execute an already compiled bytecode module
python -m rifai disasm program.rbc
python -m rifai vm program.rbc
~~~

The vm command executes an existing .rbc file. Source compilation is intentionally reserved for Phase 4.

## Bytecode Format

Rifa'i bytecode version 1 uses a RIFAI-RBC magic header followed by a UTF-8 JSON payload. The payload stores a format version, typed constants, the main code chunk, instruction operands, and optional source-map locations. The serializer rejects unknown versions and malformed structures; the verifier checks opcodes, operands, jump targets, stack effects, and control-flow merge consistency before execution.

## Setup & Testing

~~~bash
python -m venv .venv
# Activate the environment, then:
pip install -e ".[dev]"
python -m pytest -v
~~~
