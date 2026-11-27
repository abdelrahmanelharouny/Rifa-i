# Rifa'i

Rifa'i (.rif) is a custom statically typed programming language implemented in Python. Source programs compile to a versioned custom stack-based bytecode format (.rbc), executed by the Rifa'i Virtual Machine.

## Development Status

- **Phase 1 — Language and Lexer (Complete):** Language specification, formal EBNF grammar, token system, lexer, source positions, diagnostics, and token inspection.
- **Phase 2 — Frontend (Complete):** Immutable AST, recursive-descent parser, symbol table, lexical scopes, strict static type checking, forward function references, and definite-return analysis.
- **Phase 3 — Bytecode and VM Core (Complete):** Versioned bytecode container, typed constant pool, instruction set, verifier, serializer, disassembler, and stack-based VM core.
- **Phase 4 — Code Generation and Full Execution (Complete):** AST-to-bytecode compiler, globals and local slots, control flow, function chunks, call frames, recursion, end-to-end source compilation, and compile / run CLI commands.
- **Phase 5 — Optimization and Final Hardening (Complete):** Conservative bytecode optimization, bounded VM resources, hardened bytecode validation and atomic serialization, reproducible performance benchmarks, final examples, and delivery documentation.

## Quick Start

```bash
python -m venv .venv
# Activate the environment, then:
pip install -e ".[dev]"

# Compile a Rifa'i program to a portable .rbc file (optimization is on by default)
python -m rifai compile examples/phase5_optimization.rif

# Run source directly (compile in memory, then execute)
python -m rifai run examples/phase5_optimization.rif

# Compile without optimization for debugging/comparison
python -m rifai compile examples/phase5_optimization.rif --no-optimize

# Run an already compiled bytecode file
python -m rifai run examples/phase5_optimization.rbc

# Inspect compiled bytecode
python -m rifai disasm examples/phase5_optimization.rbc

# Run the complete test suite
python -m pytest -v
```

## CLI Reference

| Command | Purpose |
|---|---|
| rifai tokens file.rif | Inspect lexer output |
| rifai parse file.rif | Parse source and validate syntax |
| rifai ast file.rif | Print the AST |
| rifai check file.rif | Run semantic validation |
| rifai compile file.rif [-o out.rbc] [--no-optimize] | Compile source into bytecode |
| rifai run file.rif [--no-optimize] | Compile and execute source |
| rifai run file.rbc | Execute an existing bytecode module |
| rifai disasm file.rbc | Verify and disassemble bytecode |
| rifai vm file.rbc | Execute an existing bytecode module |

## Phase 5: Optimization

The compiler enables a conservative bytecode optimization pass by default. It folds constant unary and binary expressions, deduplicates constants using both their exact type and value, removes unreferenced constant-pool entries, and removes the stack-neutral `DUP; POP` pair. The pass runs on the main chunk and every function chunk.

The optimizer intentionally leaves operations that can raise at runtime (such as division or modulo by zero) untouched. When compacting instructions, the optimizer remaps absolute jump targets and preserves source locations. It refuses to fold an expression if a jump enters the middle of that expression, and it does not remove a DUP/POP pair when a jump targets either instruction. The generated module is verified again after optimization. Use `Compiler(optimize=False)` or the CLI `--no-optimize` flag to compare output or investigate generated instructions.

## Runtime and File Hardening

The VM bounds instruction count, operand-stack depth, call depth, local-frame size, integer bit length, individual string length, and total captured output. Limits are configurable through `VirtualMachine(...)`. Invalid limit values and malformed initial-global inputs are rejected explicitly.

Bytecode deserialization enforces the 16 MiB file limit and validates the complete input before execution. File writes use a temporary file in the destination directory followed by an atomic replacement, avoiding partially written `.rbc` files. The verifier also validates source-map coordinates and enforces structural complexity limits.

## Benchmarks

Run `python benchmarks/benchmark_pipeline.py` to compare optimized and unoptimized compilation output and VM execution. Use `--iterations` and `--repeat` to scale the workload and sampling. The benchmark checks semantic output parity and reports local median/best timings; it does not impose unstable timing assertions in CI. See [benchmarks/README.md](benchmarks/README.md).

## Phase 4 Capabilities

The code generator consumes the same AST instances and SemanticResult bindings produced by the frontend. It does not repeat name resolution. Symbols are mapped to deterministic local slots or global names, preserving lexical shadowing and nested block scope.

Each function is compiled into its own code chunk. Calls use isolated call frames with independent instruction pointers and local arrays. Arguments are checked against the function signature; recursive and mutually recursive calls are supported. Return values are passed back on the caller's operand stack.

The bytecode format is version 2. The reader retains support for version 1 modules that do not contain function chunks. Version 2 modules store function signatures and code chunks in a function table.

## Testing

The suite covers lexical and syntactic analysis, semantic errors, bytecode verification and serialization, VM operations, source compilation, control flow, local/global variables, function calls, recursion, optimization parity, optimizer invariants, resource limits, and CLI workflows.

```bash
python -m pytest -v
```
