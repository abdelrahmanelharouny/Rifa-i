# Rifa'i Compiler Architecture

Rifa'i is a statically typed language implemented in Python. Its compiler translates .rif source files into custom .rbc bytecode, which is verified, serialized, and executed by the Rifa'i VM.

## 1. Complete Pipeline

```text
  .rif source
      |
      v
  Lexer ---------------------------- Phase 1
      | tokens + lexical diagnostics
      v
  Recursive-Descent Parser ---------- Phase 2
      | immutable AST
      v
  Semantic Analyzer ---------------- Phase 2
      | type information + exact symbol bindings
      v
  AST-to-Bytecode Code Generator ---- Phase 4
      | main chunk + function chunks + constant pool
      v
  Bytecode Optimizer ---------------- Phase 5
      | constant folding + constant-pool compaction
      v
  CFG Analysis --------------------- Phase 9
      | basic blocks + reachability
      v
  Bytecode Verifier ---------------- Phase 3/4/5
      | validated control flow and stack effects
      v
  Bytecode Serializer -------------- Phase 3/5
      | versioned .rbc module
      v
  Rifa'i Virtual Machine ----------- Phase 3/4/5
      | bounded execution + output + global state
      v
  Program result
```

Compiler.compile() orchestrates the frontend, code generator, optional optimizer, and final verifier. It stops at the first failing phase and returns structured diagnostics. Optimized bytecode is verified again before it is exposed as a successful compilation result.

## 2. Package Layout

- rifai/frontend/: Token models, Lexer, immutable AST, Parser, types, symbol table, and Semantic Analyzer.
- rifai/bytecode/instructions.py: Opcode definitions, operand contracts, and stack effects.
- rifai/bytecode/chunk.py: Main/function code chunks and function signature metadata.
- rifai/bytecode/module.py: Bytecode module, constants, version information, and function table.
- rifai/bytecode/codegen.py: AST-to-bytecode generation using SemanticResult bindings.
- rifai/bytecode/optimizer.py: Semantics-preserving constant folding, no-op cleanup, and constant-pool compaction.
- rifai/bytecode/cfg.py: Deterministic basic-block construction, control-flow edges, and entry-reachability analysis.
- rifai/bytecode/verifier.py: Operand validation, source-map validation, module limits, and per-chunk control-flow stack analysis.
- rifai/bytecode/serializer.py: Deterministic versioned .rbc serialization and atomic file writes.
- rifai/bytecode/disassembler.py: Readable listing of constants, main instructions, and functions.
- rifai/compiler.py: End-to-end source-to-bytecode compiler orchestration.
- rifai/vm/machine.py: Operand stack, local/global storage, control flow, bounded output, and call-frame interpreter.
- rifai/vm/runtime.py: Runtime results and diagnostics.
- rifai/cli.py: Frontend inspection, compilation, disassembly, and execution commands.

## 3. Code Generation

The generator receives the exact Program object and corresponding SemanticResult. It consumes identity-keyed semantic bindings for variable declarations, assignments, variable references, function declarations, and function calls. It does not redo scope lookup or infer types.

Global variables use named global slots. Variables in function scopes and nested lexical blocks use deterministic zero-based local slots within the active code chunk. Distinct shadowed declarations receive distinct slots, so the nearest lexical binding remains the one selected by semantic analysis.

The generator emits constants into a deduplicated typed constant pool, arithmetic/comparison/equality/logical instructions, local/global loads and stores, conditional and unconditional jumps for if/else-if/while, one function chunk per top-level function, CALL and RETURN instructions, and source locations on emitted instructions.

Logical and/or retain the language's eager evaluation semantics in version 1. The generator evaluates left then right operands before the logical opcode.

## 4. Function Calls and VM Frames

A version 2 bytecode module contains one main chunk and a function table. Each function table entry stores a function name, parameter types, return type, and code chunk. The first arity local slots are reserved for parameters, in declaration order.

The VM uses a shared operand stack and a separate call-frame stack. Each frame owns its code chunk, instruction pointer, local storage, return convention, and operand-stack baseline. CALL removes its arguments from the operand stack, validates them against the function signature, creates a new frame, and transfers control. RETURN restores the caller and pushes a result only for non-void functions.

Function chunks can call any function in the module, including themselves and functions declared later. This supports direct recursion, mutual recursion, and forward references. A configurable call-depth limit prevents unbounded recursion from exhausting the host stack; execution, operand-stack, string-size, and captured-output limits are also enforced.

## 5. Bytecode Versions

- Version 1: Main chunk only; retained as a readable and executable legacy format.
- Version 2: Adds a function table with typed signatures and function chunks, plus CALL and RETURN instructions.

The serializer writes version 2 by default and continues to read version 1. The verifier checks the main chunk and every function chunk independently, including call targets, arity, local slots, jump targets, stack underflow, stack-height merge consistency, return-stack discipline, terminal instructions, source-map coordinates, and structural complexity bounds.

## 6. Optimization

Optimization runs after code generation and before the final bytecode verification. The conservative pass folds pure constant unary/binary operations when the result is finite and within compile-time folding bounds. It removes unused constants and deduplicates by exact type and value, preserving the distinction between values such as `true` and `1`. It also removes the neutral `DUP; POP` sequence.

The pass compacts folded expressions and no-op pairs, then remaps absolute jump targets to the compacted instruction indices. It refuses to fold a range if a jump enters its interior, and it keeps a DUP/POP pair when either instruction is a jump target. Division/modulo by zero and operations whose result is outside the folding bounds remain instructions and preserve runtime diagnostics. Optimization can be disabled with `Compiler(optimize=False)` or `--no-optimize`.

## 7. Control-Flow Analysis

Phase 9 adds a read-only control-flow graph (CFG) for the main bytecode chunk and each function chunk. Leaders are the entry instruction, jump targets, and instructions immediately following conditional/unconditional branches or terminators. Each basic block is represented by its first and last instruction offsets; successors encode branch and fall-through edges. A breadth-first traversal from the entry block classifies reachable and unreachable blocks. The analysis does not rewrite bytecode, alter stack behavior, or change the serialized v4 format.

`rifai inspect` exports the CFG under `stages.bytecode.control_flow`, including block ranges, successors, edge counts, and reachable/unreachable instruction totals. This gives compiler tooling and future optimization passes a stable control-flow foundation without coupling analysis to execution.

## 8. Diagnostics, Limits, and CLI

Diagnostics identify the phase that emitted them and preserve source line/column coordinates when available. Generated instructions carry source locations into the VM. The VM exposes configurable positive-integer limits for executed instructions, operand-stack depth, call depth, integer bit length, string length, and total captured output. The verifier also bounds local slots per code chunk and constant-string sizes. The serializer caps bytecode files at 16 MiB and writes files using a temporary file plus atomic replacement.

- tokens, parse, ast, and check inspect or validate source.
- compile source.rif [-o output.rbc] [--no-optimize] compiles and saves bytecode.
- run source.rif [--no-optimize] compiles in memory and executes immediately.
- run program.rbc and vm program.rbc execute an existing bytecode module.
- disasm program.rbc validates and displays bytecode.

## 10. Project Phases

- Phase 1: Language specification and Lexer.
- Phase 2: AST, Parser, Symbol Table, and Semantic Analyzer.
- Phase 3: Bytecode model, serializer, verifier, disassembler, and VM core.
- Phase 4: AST-to-bytecode code generation, function chunks, call frames, and full source execution.
- Phase 5: Conservative optimization, runtime and bytecode hardening, reproducible benchmarks, examples, and final delivery.
- Phase 9: Bytecode control-flow graph construction, basic-block and edge modeling, reachability analysis, and structured inspection output.
- Phase 10: CFG-aware constant propagation, branch simplification, unreachable-block elimination, and profitable local common-subexpression elimination.
