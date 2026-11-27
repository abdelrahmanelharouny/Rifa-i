# Rifa'i

Rifa'i (.rif) is a custom statically typed programming language implemented in Python. Source programs compile to a versioned custom stack-based bytecode format (.rbc), executed by the Rifa'i Virtual Machine.

## Development Status

- **Phase 1 — Language and Lexer (Complete):** Language specification, formal EBNF grammar, token system, lexer, source positions, diagnostics, and token inspection.
- **Phase 2 — Frontend (Complete):** Immutable AST, recursive-descent parser, symbol table, lexical scopes, strict static type checking, forward function references, and definite-return analysis.
- **Phase 3 — Bytecode and VM Core (Complete):** Versioned bytecode container, typed constant pool, instruction set, verifier, serializer, disassembler, and stack-based VM core.
- **Phase 4 — Code Generation and Full Execution (Complete):** AST-to-bytecode compiler, globals and local slots, control flow, function chunks, call frames, recursion, end-to-end source compilation, and compile / run CLI commands.
- **Phase 5 — Optimization and Final Hardening (Complete):** Conservative bytecode optimization, bounded VM resources, hardened bytecode validation and atomic serialization, reproducible performance benchmarks, final examples, and delivery documentation.
- **Phase 6 — Developer Experience (Complete):** stdio Language Server Protocol implementation, VS Code language extension, live diagnostics, completion, hover, definition/references, document symbols, signature help, and structured compiler-pipeline inspection.
- **Phase 7 — Debugging Toolchain (Complete):** Interactive CLI debugger and VS Code Debug Adapter Protocol integration, source breakpoints, step into/over/out, locals/globals/operand-stack inspection, call stack, and standalone .rbc debugging with embedded source and local-symbol metadata.
- **Phase 8 — Typed Collections (Complete):** Homogeneous one-dimensional arrays (int[], float[], bool[], string[]), literals, indexing, element assignment, array parameters/returns, standard len/push/pop, runtime bounds and capacity checks, and bytecode v4.
- **Phase 9 — Control-Flow Analysis (Complete):** Deterministic bytecode basic blocks, branch/fall-through edges, per-chunk reachability analysis, and structured CFG export through `rifai inspect`.

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
rifai debug examples/phase7_debugger.rif --breakpoint 4

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
| rifai debug file.rif or file.rbc [-b line] [--no-optimize] | Start the interactive debugger |
| rifai debug-adapter | Start the VS Code Debug Adapter Protocol server over stdio |
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

The suite covers lexical and syntactic analysis, semantic errors, typed-array construction/indexing/mutation, standard collection functions, bytecode verification and serialization, VM operations, source compilation, control flow, local/global variables, function calls, recursion, optimization parity, optimizer invariants, resource limits, and CLI workflows.

```bash
python -m pytest -v
```


## Phase 6: Developer Experience

Rifa'i now includes a dependency-free Python Language Server using JSON-RPC 2.0 and Content-Length framed stdio. It supports document open/change/close, full-document synchronization, UTF-16 position conversion, live lexer/parser/semantic diagnostics, completions, hover type and signature information, go to definition, references, document symbols, and function signature help. Open-document versions are checked so stale changes are ignored. The server can be launched with `rifai-lsp` or `rifai lsp`.

The VS Code extension lives in [editors/vscode](editors/vscode). It provides `.rif` file association, syntax highlighting, language configuration, snippets, and LSP client integration. Install the Python package in the selected environment with `pip install -e .`, then set **Rifa'i: Server Path** to the `rifai` executable when it is not on PATH.

Use `rifai inspect examples/hello.rif -o hello.inspect.json` to export a versioned JSON snapshot containing tokens and source offsets, the structured AST, global semantic symbols, inferred expression types, constants, main and function bytecode chunks, disassembly, optimization statistics, and source diagnostics. The schema is designed as a stable foundation for an interactive Compiler Explorer or Rifa'i Studio frontend.

Editor integration details and packaging instructions are documented in [editors/vscode/README.md](editors/vscode/README.md) and [docs/phase6-report.md](docs/phase6-report.md).


## Phase 7: Debugging Toolchain

Run `rifai debug program.rif` or `rifai debug program.rbc` to start the CLI debugger. Bytecode v3 embeds optional source text and per-chunk local-slot names/types, so standalone `.rbc` files can be debugged after the original source is removed. Legacy v1/v2 bytecode remains readable and executable; older files do not contain the source-level metadata.

The VS Code extension registers a Debug Adapter Protocol implementation. Open a `.rif` file, select **Debug current Rifa'i file**, and press F5; or create a `rifai` launch configuration pointing to a compiled `.rbc` file. The adapter supports entry and source-line breakpoints, continue, pause, step over/into/out, call-stack frames, locals, globals, operand stack, and embedded source retrieval. Hover/evaluate reads a direct variable name only; it does not execute arbitrary expressions.

The VM exposes immutable pre-instruction snapshots shared by both debugger interfaces. The optimizer preserves embedded metadata because local slots are not renumbered. Use `--no-optimize` in the CLI or `noOptimize` in `launch.json` to follow the direct code-generator instruction sequence. See [docs/phase7-report.md](docs/phase7-report.md) and [editors/vscode/README.md](editors/vscode/README.md).


## Phase 8: Typed Collections

Rifa'i supports statically typed homogeneous one-dimensional arrays. Supported element types are int, float, bool, and string. The type annotations are int[], float[], bool[], and string[].

Example:

```rif
let numbers: int[] = [10, 20, 30];
print(numbers[1]);
numbers[1] = 25;
push(numbers, 40);
print(pop(numbers));
print(len(numbers));
```

Non-empty literals infer the element type and require exact homogeneity. Empty literals are permitted when their surrounding declaration/parameter/return type supplies the element type. Arrays can be passed to and returned from functions. They are reference values, so aliases observe mutations. Nested arrays are intentionally unsupported.

The standard collection functions are len(string or T[]) -> int, push(T[], T) -> void, and pop(T[]) -> T. Array indexes are zero-based. The VM checks element types, bounds, empty pops, and a configurable max_array_items limit.

Bytecode v4 adds typed array construction, element access/mutation, length, append, and pop instructions. Bytecode v1, v2, and v3 remain readable and executable; collection instructions are rejected in formats older than v4. See docs/phase8-report.md, docs/language-spec.md, and docs/bytecode-spec.md.


## Phase 9: Control-Flow Graph Analysis

Rifa'i builds a read-only control-flow graph for the main chunk and every function. The graph splits bytecode at entry points, branch targets, and instructions following branch/terminal instructions. It records basic-block ranges and successor edges, then computes entry reachability to identify unreachable blocks and instruction counts.

Inspect the result with:

```bash
rifai inspect examples/phase8_collections.rif -o phase9.inspect.json
```

The JSON report includes `stages.bytecode.control_flow`, keyed by chunk name. Each graph reports block and edge counts, block offsets, successors, reachability, and reachable/unreachable instruction totals. CFG analysis is deliberately non-mutating: it does not change bytecode, debug mappings, runtime behavior, or the v4 file format. See [docs/phase9-report.md](docs/phase9-report.md).
