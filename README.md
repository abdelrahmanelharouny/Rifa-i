# Rifa'i

Rifa'i (.rif) is a custom statically typed programming language implemented in Python. Source programs compile to a versioned custom stack-based bytecode format (.rbc), executed by the Rifa'i Virtual Machine.

## Development Status

- **Phase 1 — Language and Lexer (Complete):** Language specification, formal EBNF grammar, token system, lexer, source positions, diagnostics, and token inspection.
- **Phase 2 — Frontend (Complete):** Immutable AST, recursive-descent parser, symbol table, lexical scopes, strict static type checking, forward function references, and definite-return analysis.
- **Phase 3 — Bytecode and VM Core (Complete):** Versioned bytecode container, typed constant pool, instruction set, verifier, serializer, disassembler, and stack-based VM core.
- **Phase 4 — Code Generation and Full Execution (Complete):** AST-to-bytecode compiler, globals and local slots, control flow, function chunks, call frames, recursion, end-to-end source compilation, and compile / run CLI commands.
- **Phase 5 — Optimization and Final Hardening (Complete):** Conservative bytecode optimization, bounded VM resources, hardened bytecode validation and atomic serialization, reproducible performance benchmarks, final examples, and delivery documentation.
- **Phase 6 — Developer Experience (Complete):** stdio Language Server Protocol implementation, VS Code language extension, live diagnostics, completion, hover, definition/references, document symbols, signature help, and structured compiler-pipeline inspection.
- **Phase 7 — Interactive Debugger (Complete):** Source-mapped breakpoints, step into/over/out, instruction stepping, live locals/globals/operand-stack inspection, call-stack backtraces, and source-level local variable names without changing the bytecode format.

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

# Debug source execution with the interactive debugger
rifai debug examples/phase7_debugger.rif --breakpoint 3

# Export the complete compiler pipeline as structured JSON
rifai inspect examples/hello.rif -o hello.inspect.json

# Start the Language Server (VS Code runs this over stdio)
rifai-lsp
# or: rifai lsp

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
| rifai inspect file.rif [-o report.json] [--no-optimize] | Export tokens, AST, semantic bindings, bytecode, and optimization data as JSON |
| rifai debug file.rif [-b line] [--no-optimize] | Start the interactive source debugger |
| rifai lsp | Start the stdio Language Server |

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


## Phase 6: Developer Experience

Rifa'i now includes a dependency-free Python Language Server using JSON-RPC 2.0 and Content-Length framed stdio. It supports document open/change/close, full-document synchronization, UTF-16 position conversion, live lexer/parser/semantic diagnostics, completions, hover type and signature information, go to definition, references, document symbols, and function signature help. Open-document versions are checked so stale changes are ignored. The server can be launched with `rifai-lsp` or `rifai lsp`.

The VS Code extension lives in [editors/vscode](editors/vscode). It provides `.rif` file association, syntax highlighting, language configuration, snippets, and LSP client integration. Install the Python package in the selected environment with `pip install -e .`, then set **Rifa'i: Server Path** to the `rifai` executable when it is not on PATH.

Use `rifai inspect examples/hello.rif -o hello.inspect.json` to export a versioned JSON snapshot containing tokens and source offsets, the structured AST, global semantic symbols, inferred expression types, constants, main and function bytecode chunks, disassembly, optimization statistics, and source diagnostics. The schema is designed as a stable foundation for an interactive Compiler Explorer or Rifa'i Studio frontend.

Editor integration details and packaging instructions are documented in [editors/vscode/README.md](editors/vscode/README.md) and [docs/phase6-report.md](docs/phase6-report.md).


## Phase 7: Interactive Debugger

Run **rifai debug program.rif** to start a source-aware debugging session. The debugger pauses before the first instruction and accepts commands at the `(rifai-debug)` prompt. Add one or more initial line breakpoints with `-b 12` or `--breakpoint 12`.

| Command | Action |
|---|---|
| `continue` / `c` | Continue until the next breakpoint |
| `step` / `s` | Step into the next source expression or function call |
| `next` / `n` | Step over the current source expression or call |
| `out` / `finish` | Run until the current function returns |
| `stepi` | Execute one bytecode instruction |
| `break 12` / `delete 12` | Add or remove a source-line breakpoint |
| `locals`, `globals`, `stack` | Inspect current variables and operand stack |
| `backtrace` / `bt` | Inspect active function call frames |
| `list`, `where` | Show nearby source and current instruction |
| `help`, `quit` | Show commands or stop debugging |

The VM exposes an optional immutable pre-instruction observer API. The compiler carries source-level local names and types as transient debug metadata alongside a compilation result; this metadata is not serialized into `.rbc`, so bytecode v1/v2 compatibility and the file format remain unchanged. Source-level debugging is therefore available for `.rif` inputs compiled in the current process. When optimization is disabled with `--no-optimize`, stepping follows the direct code-generator instruction sequence, which is useful when investigating compiler output.

See [docs/phase7-report.md](docs/phase7-report.md) for implementation notes and limitations.
