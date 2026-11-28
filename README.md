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
- **Phase 10 — Data-Flow & Advanced Optimization (Complete):** CFG-aware constant propagation, constant-branch folding, unreachable-block elimination, profitable block-local common-subexpression elimination, and optimization statistics.
- **Phase 11 — Intermediate Representation (Complete):** Typed explicit-value IR, basic-block parameters, bytecode-to-IR and IR-to-bytecode lowering, IR verification, canonical value numbering, dominator/loop analysis, and multi-pass compiler integration.
- **Phase 12 — IR-Native Optimization (Complete):** Scalar constant propagation through IR values and block parameters, bounded constant folding, constant-branch simplification, unreachable-block elimination, fixed-point optimization, and verified lowering. `Compiler(optimize=False)` / `--no-optimize` disables both bytecode and IR transformations; `ir_optimize` can override the IR layer for isolated evaluation.
- **Phase 13 — Direct AST-to-IR Compilation (Complete):** The normal source compiler now lowers the semantically-bound AST directly into typed IR, builds explicit control-flow blocks and function bodies, preserves source/debug metadata, verifies and optimizes IR, then lowers to the versioned bytecode backend (v5 for the new nominal-type features). Bytecode-to-IR lifting remains available as a compatibility and round-trip API.
- **Phase 14 — Advanced IR Optimization (Complete):** Dominance-aware global common-subexpression elimination, copy propagation, conservative dead-code elimination, natural-loop LICM, explicit side-effect/trap classification, dominance verification for cross-block values, and materialized-value bytecode lowering for safe multi-use/loop-carried values. All transformations preserve the v4 bytecode contract used at the time of Phase 14.
- **Phase 15 — Language Evolution (Complete):** Relative source modules with dependency ordering/cycle and traversal checks; nominal structs and unit enums; inferred local variables; field access and mutation; checked math/string/conversion/file standard-library functions; capability-based bounded UTF-8 file I/O; and bytecode v5 with continued v1-v4 compatibility.
- **Phase 16 — Advanced Control Flow (Complete):** C-style for loops with scoped initializers and optional clauses; break/continue with correct nested-loop targets; and true short-circuit and/or lowering through explicit IR branches and block parameters.
- **Phase 17 — Algebraic Data Types & Pattern Matching (Complete):** Typed enum payload variants, immutable tagged runtime values, exhaustive enum match expressions with scoped payload bindings, explicit IR decision trees, and bytecode v6 with v1–v5 compatibility.

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

# Run the Phase 15 language example
rifai run examples/phase15_language_evolution.rif

# Run the Phase 16 advanced control-flow example
rifai run examples/phase16_advanced_control_flow.rif

# Run the Phase 17 algebraic data types example
rifai run examples/phase17_algebraic_data_types.rif

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

The VM bounds instruction count, operand-stack depth, call depth, local-frame size, integer bit length, individual string length, total captured output, array items, and file bytes. File I/O is disabled in the embedded VM API unless the host supplies an explicit project-root capability. Limits are configurable through `VirtualMachine(...)`. Invalid limit values and malformed initial-global inputs are rejected explicitly.

Bytecode deserialization enforces the 16 MiB file limit and validates the complete input before execution. File writes use a temporary file in the destination directory followed by an atomic replacement, avoiding partially written `.rbc` files. The verifier also validates source-map coordinates and enforces structural complexity limits.

## Benchmarks

Run `python benchmarks/benchmark_pipeline.py` to compare optimized and unoptimized compilation output and VM execution. Use `--iterations` and `--repeat` to scale the workload and sampling. The benchmark checks semantic output parity and reports local median/best timings; it does not impose unstable timing assertions in CI. See [benchmarks/README.md](benchmarks/README.md).

## Phase 4 Capabilities

The code generator consumes the same AST instances and SemanticResult bindings produced by the frontend. It does not repeat name resolution. Symbols are mapped to deterministic local slots or global names, preserving lexical shadowing and nested block scope.

Each function is compiled into its own code chunk. Calls use isolated call frames with independent instruction pointers and local arrays. Arguments are checked against the function signature; recursive and mutually recursive calls are supported. Return values are passed back on the caller's operand stack.

The bytecode format is version 2. The reader retains support for version 1 modules that do not contain function chunks. Version 2 modules store function signatures and code chunks in a function table.

## Testing

The suite covers lexical and syntactic analysis, nominal types, imports, inferred declarations, typed-array construction/indexing/mutation, standard-library functions, sandboxed file I/O, bytecode versions 1–6, VM operations, source compilation, control flow, local/global variables, function calls, recursion, optimization parity, optimizer invariants, resource limits, and CLI workflows.

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


## Phase 10: Data-Flow and Advanced Optimization

The optimizer now uses the Phase 9 CFG to propagate constant scalar values through basic blocks and merge facts conservatively at control-flow joins. A value remains known only when every reachable incoming path agrees on both its exact type and value. Known boolean conditions are lowered to an unconditional path, and unreachable blocks are removed while preserving required main/function terminators.

A block-local common-subexpression pass reuses repeated pure scalar expressions through compiler-managed local slots. It only keeps a cache when a later matching expression actually reuses it, invalidates entries when source locals change, never carries them across block boundaries, and does not treat mutable arrays or function calls as pure expressions. Global constant facts are invalidated by calls because a callee may update globals.

The optimizer retains the original conservative constant folding and DUP/POP cleanup, then verifies the resulting bytecode. It preserves source locations and debugger metadata, records generated temporary locals, keeps bytecode v1-v4 compatibility, and remains idempotent. Data-flow and CSE statistics are included in OptimizationStats and rifai inspect output.

Try the complete example:

```bash
rifai check examples/phase10_advanced_optimization.rif
rifai run examples/phase10_advanced_optimization.rif
rifai inspect examples/phase10_advanced_optimization.rif -o phase10.inspect.json
```

See [docs/phase10-report.md](docs/phase10-report.md) for implementation details and safety boundaries.


## Phase 11: Intermediate Representation and Multi-Pass Compiler

Rifa'i now exposes a typed, explicit-value IR between compiler optimization and final bytecode verification. The current transitional frontend keeps the proven AST-to-bytecode generator, then lifts its verified output into IR. Operand-stack values become virtual values, stack merges become block parameters, and jumps/branches/returns become explicit terminators. Local and global storage remain explicit operations, preserving the language's existing execution model.

The IR pipeline runs input verification, deterministic virtual-value numbering, output verification, and CFG analysis. The analyzer reports reachability, predecessors, dominator sets, immediate dominators, and loop back-edges for the main function and every function. The IR lowerer then reconstructs bytecode and verifies it before the compiler returns a successful result.

The final CompilationResult exposes ir_module, ir_stats, and ir_analysis. The same structured data is available from rifai inspect under stages.ir, stages.ir_pipeline, and stages.ir_analysis. Source locations, debug locals, function signatures, bytecode v1-v4 compatibility, and serialized .rbc format are preserved.

Example:

```python
from rifai import Compiler, IRVerifier

result = Compiler().compile("print(20 + 22);")
assert result.is_success
assert IRVerifier().verify(result.ir_module).is_valid
print(result.ir_module.as_dict())
print(result.ir_analysis.as_dict())
```

The direct IR API is documented in docs/phase11-report.md.


## Phase 15: Language Evolution

Phase 15 adds source imports, nominal records/enums, local type inference, and standard-library functions. Imports are relative to the importing file, remain inside the root project directory, and are compiled in dependency-first order into one global namespace. Import cycles, traversal, duplicate declarations, and oversized module graphs are rejected.

Structs use positional construction and dot-field reads/writes; they are mutable reference values. Enums expose immutable unit variants and same-type equality. Local declarations may omit their type annotation when the initializer provides an unambiguous type. Primitive arrays retain their existing type and runtime rules.

The standard library now includes math and conversion helpers, string search/slicing, and text file operations. File access is a VM capability: embedded hosts must explicitly enable it and set a root directory. CLI and debugger sessions restrict it to the launched program directory. Reads and writes are UTF-8 and capped at 1 MiB by default.

Bytecode v5 adds STRUCT_NEW, FIELD_GET, FIELD_SET, and ENUM_NEW, and supports nominal types in function signatures/debug metadata. The serializer, verifier, and VM continue to support v1-v4 modules. See [docs/phase15-report.md](docs/phase15-report.md), [docs/language-spec.md](docs/language-spec.md), and [docs/grammar.ebnf](docs/grammar.ebnf).
