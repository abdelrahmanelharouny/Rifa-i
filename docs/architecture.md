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
  Direct AST-to-IR Lowerer ---------- Phase 13
      | typed virtual values + explicit control-flow blocks
      v
  IR Multi-Pass Manager ------------- Phases 11/12
      | verify + optimize + canonicalize + analyze
      v
  IR-to-Bytecode Lowerer ------------ Phases 11/13
      | verified stack-bytecode module
      v
  Bytecode Backend Optimizer -------- Phases 5/10
      | target-specific cleanup and constant-pool compaction
      v
  Bytecode Verifier ---------------- Phases 3/4/5/11/13

  Bytecode Serializer -------------- Phase 3/5
      | versioned .rbc module
      v
  Rifa'i Virtual Machine ----------- Phase 3/4/5
      | bounded execution + output + global state
      v
  Program result
```

Compiler.compile() now orchestrates the frontend, direct AST-to-IR lowering, IR verification/optimization/analysis, IR-to-bytecode lowering, optional target-specific bytecode cleanup, and final bytecode verification. It stops at the first failing phase and returns structured diagnostics. The normal source-compilation path no longer generates bytecode as an intermediate input to IR. BytecodeToIR remains available for lifting existing verified modules, compatibility checks, and round-trip tooling.

## 2. Package Layout

- rifai/frontend/: Token models, Lexer, immutable AST, Parser, types, symbol table, and Semantic Analyzer.
- rifai/bytecode/instructions.py: Opcode definitions, operand contracts, and stack effects.
- rifai/bytecode/chunk.py: Main/function code chunks and function signature metadata.
- rifai/bytecode/module.py: Bytecode module, constants, version information, and function table.
- rifai/bytecode/codegen.py: AST-to-bytecode generation using SemanticResult bindings.
- rifai/bytecode/optimizer.py: Semantics-preserving constant folding, no-op cleanup, and constant-pool compaction.
- rifai/bytecode/cfg.py: Deterministic basic-block construction, control-flow edges, and entry-reachability analysis.
- rifai/ir/ast_to_ir.py: Direct source-AST-to-IR lowering using semantic bindings, typed local slots, explicit basic blocks, and source locations.
- rifai/ir/: Typed explicit-value IR models, compatibility bytecode lifting, IR verification, canonical value numbering, dominator analysis, and the pass manager.
- rifai/bytecode/verifier.py: Operand validation, source-map validation, module limits, and per-chunk control-flow stack analysis.
- rifai/bytecode/serializer.py: Deterministic versioned .rbc serialization and atomic file writes.
- rifai/bytecode/disassembler.py: Readable listing of constants, main instructions, and functions.
- rifai/compiler.py: End-to-end source-to-bytecode compiler orchestration.
- rifai/vm/machine.py: Operand stack, local/global storage, control flow, bounded output, and call-frame interpreter.
- rifai/vm/runtime.py: Runtime results and diagnostics.
- rifai/cli.py: Frontend inspection, compilation, disassembly, and execution commands.

## 3. Code Generation

ASTToIR receives the exact Program object and corresponding SemanticResult. It consumes identity-keyed semantic bindings for declarations, assignments, variable references, function declarations, and function calls. It does not redo scope lookup or infer source types.

Each function and the main program receive deterministic local-slot maps. Parameters occupy the first slots, declarations in nested lexical scopes receive distinct slots, and globals remain named global operations. This preserves shadowing and debugger-visible local names without coupling the IR builder to a second name-resolution pass.

Expressions become typed virtual values and explicit-input operations. If/else-if and while statements become explicit basic blocks and terminators. Since source variables are represented by local/global loads and stores, transient expression values are block-local and control-flow edges do not need to carry hidden operand-stack state. Every operation and terminator retains its source location. The existing bytecode CodeGenerator remains available as a compatibility/reference API, but Compiler.compile() uses ASTToIR.

Logical and/or retain eager evaluation semantics in version 1: the left operand is evaluated before the right operand and the logical opcode.

## 4. Function Calls and VM Frames

A version 2 bytecode module contains one main chunk and a function table. Each function table entry stores a function name, parameter types, return type, and code chunk. The first arity local slots are reserved for parameters, in declaration order.

The VM uses a shared operand stack and a separate call-frame stack. Each frame owns its code chunk, instruction pointer, local storage, return convention, and operand-stack baseline. CALL removes its arguments from the operand stack, validates them against the function signature, creates a new frame, and transfers control. RETURN restores the caller and pushes a result only for non-void functions.

Function chunks can call any function in the module, including themselves and functions declared later. This supports direct recursion, mutual recursion, and forward references. A configurable call-depth limit prevents unbounded recursion from exhausting the host stack; execution, operand-stack, string-size, and captured-output limits are also enforced.

## 5. Bytecode Versions

- Version 1: Main chunk only; retained as a readable and executable legacy format.
- Version 2: Adds a function table with typed signatures and function chunks, plus CALL and RETURN instructions.

The serializer writes version 2 by default and continues to read version 1. The verifier checks the main chunk and every function chunk independently, including call targets, arity, local slots, jump targets, stack underflow, stack-height merge consistency, return-stack discipline, terminal instructions, source-map coordinates, and structural complexity bounds.

## 6. Optimization

Optimization is layered. The IR pass manager performs source-independent, typed scalar constant propagation/folding, constant-branch simplification, and unreachable-block removal before lowering. The bytecode optimizer then performs target-specific cleanup: conservative instruction folding, typed constant-pool deduplication/compaction, and safe stack-neutral no-op removal.

The bytecode optimizer remaps absolute jump targets after compaction and preserves source locations. It refuses unsafe folds when control flow enters the middle of an expression, and it keeps a DUP/POP pair when either instruction is a jump target. Division/modulo by zero and operations outside folding bounds remain runtime operations. Compiler(optimize=False) disables both IR and backend transformations; ir_optimize can explicitly isolate the IR pass manager.

## 7. Control-Flow Analysis

Phase 9 adds a read-only control-flow graph (CFG) for the main bytecode chunk and each function chunk. Leaders are the entry instruction, jump targets, and instructions immediately following conditional/unconditional branches or terminators. Each basic block is represented by its first and last instruction offsets; successors encode branch and fall-through edges. A breadth-first traversal from the entry block classifies reachable and unreachable blocks. The analysis does not rewrite bytecode, alter stack behavior, or change the serialized v4 format.

`rifai inspect` exports the CFG under `stages.bytecode.control_flow`, including block ranges, successors, edge counts, and reachable/unreachable instruction totals. This gives compiler tooling and future optimization passes a stable control-flow foundation without coupling analysis to execution.

## 8. Intermediate Representation and Pass Manager

Phase 11 introduced the explicit-value IR model and the compatibility BytecodeToIR lifter. The lifter verifies its input and converts operand-stack entries to typed virtual values; stack merges become target block parameters. This remains useful for inspecting, migrating, and round-tripping verified bytecode modules.

The normal source compiler now enters IR through ASTToIR, without generating bytecode first. It uses the semantic analyzer's exact symbol/type bindings and creates typed operations, function signatures, local-slot metadata, constants, and explicit basic blocks directly from the AST. If/else-if statements become conditional edges; while loops become explicit condition/body/exit blocks and back-edges. Expression temporaries are block-local, while variables remain explicit local/global memory operations, so the current IR verifier can validate definitions without implicit cross-block temporaries.

The IR verifier checks unique definitions, use-before-definition, operation arity, function call signatures, block targets, and live edge/block-parameter compatibility. IRValueNumberingPass assigns deterministic virtual-value IDs. IRAnalyzer computes reachability, predecessors, dominator sets, immediate dominators, and natural loop back-edges. The pass manager verifies IR before and after optimization/canonicalization and produces stable analysis/statistics.

IRToBytecode lays out blocks using deterministic layout indices, reconstitutes branch targets and terminators, preserves constants/local frames/source maps/debug metadata, and runs the bytecode verifier over the lowered module. No new bytecode opcodes or serialized-format changes are required. BytecodeToIR remains a public compatibility tool; Compiler.compile() uses the direct AST route.

Phase 12 adds IR-native scalar constant propagation through values and block parameters, bounded constant folding, constant-branch simplification, and reachability-based block removal. The pass manager iterates to a bounded fixed point, canonicalizes values, verifies the result, and records transformation counters. Runtime-faulting expressions and unknown branches remain intact. The target-specific BytecodeOptimizer runs after lowering when optimization is enabled. Compiler(optimize=False) disables both optimization layers while retaining verification and analysis; the optional ir_optimize override supports isolated comparisons. CompilationResult exposes ir_origin, ir_module, ir_stats, and ir_analysis; rifai inspect exports the same information under its IR stages.

## 9. Diagnostics, Limits, and CLI

Diagnostics identify the phase that emitted them and preserve source line/column coordinates when available. Generated instructions carry source locations into the VM. The VM exposes configurable positive-integer limits for executed instructions, operand-stack depth, call depth, integer bit length, string length, and total captured output. The verifier also bounds local slots per code chunk and constant-string sizes. The serializer caps bytecode files at 16 MiB and writes files using a temporary file plus atomic replacement.

- tokens, parse, ast, and check inspect or validate source.
- compile source.rif [-o output.rbc] [--no-optimize] compiles and saves bytecode.
- run source.rif [--no-optimize] compiles in memory and executes immediately.
- run program.rbc and vm program.rbc execute an existing bytecode module.
- disasm program.rbc validates and displays bytecode.

## 11. Project Phases

- Phase 1: Language specification and Lexer.
- Phase 2: AST, Parser, Symbol Table, and Semantic Analyzer.
- Phase 3: Bytecode model, serializer, verifier, disassembler, and VM core.
- Phase 4: AST-to-bytecode code generation, function chunks, call frames, and full source execution.
- Phase 5: Conservative optimization, runtime and bytecode hardening, reproducible benchmarks, examples, and final delivery.
- Phase 9: Bytecode control-flow graph construction, basic-block and edge modeling, reachability analysis, and structured inspection output.
- Phase 10: CFG-aware constant propagation, branch simplification, unreachable-block elimination, and profitable local common-subexpression elimination.
- Phase 11: Typed explicit-value IR, block parameters, verified lifting/lowering, canonical value numbering, dominator analysis, and multi-pass compiler integration.
- Phase 12: IR-native scalar constant propagation/folding, constant-branch simplification, unreachable-block elimination, and bounded fixed-point optimization.
- Phase 13: Direct semantic-AST-to-IR lowering for main/functions, explicit source-level control flow, debug metadata preservation, and direct IR-driven source compilation.
