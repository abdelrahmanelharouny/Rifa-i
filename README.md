# Rifa'i

Rifa'i (.rif) is a custom statically typed programming language implemented in Python. Source programs compile to a versioned custom stack-based bytecode format (.rbc), executed by the Rifa'i Virtual Machine.

## Development Status

- **Phase 1 — Language and Lexer (Complete):** Language specification, formal EBNF grammar, token system, lexer, source positions, diagnostics, and token inspection.
- **Phase 2 — Frontend (Complete):** Immutable AST, recursive-descent parser, symbol table, lexical scopes, strict static type checking, forward function references, and definite-return analysis.
- **Phase 3 — Bytecode and VM Core (Complete):** Versioned bytecode container, typed constant pool, instruction set, verifier, serializer, disassembler, and stack-based VM core.
- **Phase 4 — Code Generation and Full Execution (Complete):** AST-to-bytecode compiler, globals and local slots, control flow, function chunks, call frames, recursion, end-to-end source compilation, and compile / run CLI commands.
- **Phase 5 — Optimization and Final Hardening (Next):** Safe compiler optimizations, additional runtime and bytecode hardening, performance measurements, expanded examples, and final documentation.

## Quick Start

~~~bash
python -m venv .venv
# Activate the environment, then:
pip install -e ".[dev]"

# Compile a Rifa'i program to a portable .rbc file
python -m rifai compile examples/phase4_functions.rif

# Run source directly (compile in memory, then execute)
python -m rifai run examples/phase4_functions.rif

# Run an already compiled bytecode file
python -m rifai run examples/phase4_functions.rbc

# Inspect compiled bytecode
python -m rifai disasm examples/phase4_functions.rbc

# Run the complete test suite
python -m pytest -v
~~~

## CLI Reference

| Command | Purpose |
|---|---|
| rifai tokens file.rif | Inspect lexer output |
| rifai parse file.rif | Parse source and validate syntax |
| rifai ast file.rif | Print the AST |
| rifai check file.rif | Run semantic validation |
| rifai compile file.rif [-o out.rbc] | Compile source into bytecode |
| rifai run file.rif | Compile and execute source directly |
| rifai run file.rbc | Execute an existing bytecode module |
| rifai disasm file.rbc | Verify and disassemble bytecode |
| rifai vm file.rbc | Execute an existing bytecode module |

## Phase 4 Capabilities

The code generator consumes the same AST instances and SemanticResult bindings produced by the frontend. It does not repeat name resolution. Symbols are mapped to deterministic local slots or global names, preserving lexical shadowing and nested block scope.

Each function is compiled into its own code chunk. Calls use isolated call frames with independent instruction pointers and local arrays. Arguments are checked against the function signature; recursive and mutually recursive calls are supported. Return values are passed back on the caller's operand stack.

The bytecode format is version 2. The reader retains support for version 1 modules that do not contain function chunks. Version 2 modules store function signatures and code chunks in a function table.

## Testing

The suite covers lexical and syntactic analysis, semantic errors, bytecode verification and serialization, VM operations, source compilation, control flow, local/global variables, function calls, recursion, and CLI workflows.

~~~bash
python -m pytest -v
~~~
