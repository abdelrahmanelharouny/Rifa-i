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
  Generic Specializer --------------- Phase 18
      | inferred type arguments + concrete function instances
      v
  Semantic Analyzer ---------------- Phase 2
      | type information + exact symbol bindings
      v
  Direct AST-to-IR Lowerer ---------- Phase 13
      | typed virtual values + explicit control-flow blocks
      v
  IR Multi-Pass Manager ------------- Phases 11/12/14
      | verify + optimize + canonicalize + analyze
      v
  IR-to-Bytecode Lowerer ------------ Phases 11/13
      | verified stack-bytecode module
      v
  Bytecode Backend Optimizer -------- Phases 5/10
      | target-specific cleanup and constant-pool compaction
      v
  Bytecode Verifier ---------------- Phases 3/4/5/11/13/14

  Bytecode Serializer -------------- Phase 3/5
      | versioned .rbc module
      v
  Rifa'i Virtual Machine ----------- Phase 3/4/5
      | bounded execution + output + global state
      v
  Program result
```

Compiler.compile() orchestrates lexing/parsing, compile-time generic monomorphization, semantic analysis, direct AST-to-IR lowering, IR verification/optimization/analysis, IR-to-bytecode lowering, optional target-specific bytecode cleanup, and final bytecode verification. It stops at the first failing phase and returns structured diagnostics. Generic specialization emits ordinary concrete function declarations before semantic binding; no generic opcode or runtime type dispatch is introduced. The normal source-compilation path no longer generates bytecode as an intermediate input to IR. BytecodeToIR remains available for lifting existing verified modules, compatibility checks, and round-trip tooling.

## 2. Package Layout

- rifai/frontend/: Token models, Lexer, immutable AST, Parser, generic-function specializer, types, symbol table, and Semantic Analyzer.
- rifai/bytecode/instructions.py: Opcode definitions, operand contracts, and stack effects.
- rifai/bytecode/chunk.py: Main/function code chunks and function signature metadata.
- rifai/bytecode/module.py: Bytecode module, constants, version information, and function table.
- rifai/bytecode/codegen.py: AST-to-bytecode generation using SemanticResult bindings.
- rifai/bytecode/optimizer.py: Semantics-preserving constant folding, no-op cleanup, and constant-pool compaction.
- rifai/bytecode/cfg.py: Deterministic basic-block construction, control-flow edges, and entry-reachability analysis.
- rifai/ir/ast_to_ir.py: Direct source-AST-to-IR lowering using semantic bindings, typed local slots, explicit basic blocks, and source locations.
- rifai/ir/advanced_passes.py: Copy propagation, dead-code elimination, dominator-aware global CSE, and natural-loop LICM.
- rifai/ir/effects.py: Conservative operation side-effect, memory, trap, and speculation contracts.
- rifai/ir/: Typed explicit-value IR models, compatibility bytecode lifting, dominance-aware verification, canonical value numbering, dominator analysis, and the pass manager.
- rifai/bytecode/verifier.py: Operand validation, source-map validation, module limits, and per-chunk control-flow stack analysis.
- rifai/bytecode/serializer.py: Deterministic versioned .rbc serialization and atomic file writes.
- rifai/bytecode/disassembler.py: Readable listing of constants, main instructions, and functions.
- rifai/compiler.py: End-to-end source-to-bytecode compiler orchestration.
- rifai/vm/machine.py: Operand stack, local/global storage, control flow, bounded output, and call-frame interpreter.
- rifai/vm/runtime.py: Runtime results and diagnostics.
- rifai/cli.py: Frontend inspection, compilation, disassembly, and execution commands.

## 3. Compile-Time Generics

Phase 18 accepts function type parameters such as `fn identity<T>(value: T) -> T`. At each call, the GenericSpecializer infers type arguments from concrete argument expressions and creates a deterministic specialization keyed by the generic function and ordered type tuple. Repeated calls with the same tuple reuse the same generated declaration. A specialization is cached before its body is recursively rewritten, which supports self-recursion and generic-to-generic calls.

The specializer substitutes type variables in parameter, return, and local annotations, tracks concrete local types through lexical scopes, and rewrites generic calls to their specialized function names. The ordinary SemanticAnalyzer then validates the specialized body using existing type and symbol rules. Each specialization reaches ASTToIR as a normal function, so IR verification, optimization, bytecode generation, debugger metadata, and VM call-frame checks need no generic-specific behavior.

Inference failures, conflicting type arguments, non-inferable type parameters, and unsupported nested arrays produce source diagnostics before IR lowering. Generic instantiations are compile-time artifacts and are not represented in serialized bytecode metadata.

## 4. Code Generation

ASTToIR receives the exact Program object and corresponding SemanticResult. It consumes identity-keyed semantic bindings for declarations, assignments, variable references, function declarations, and function calls. It does not redo scope lookup or infer source types.

Each function and the main program receive deterministic local-slot maps. Parameters occupy the first slots, declarations in nested lexical scopes receive distinct slots, and globals remain named global operations. This preserves shadowing and debugger-visible local names without coupling the IR builder to a second name-resolution pass.

Expressions become typed virtual values and explicit-input operations. If/else-if and while statements become explicit basic blocks and terminators. Since source variables are represented by local/global loads and stores, transient expression values are block-local and control-flow edges do not need to carry hidden operand-stack state. Every operation and terminator retains its source location. The existing bytecode CodeGenerator remains available as a compatibility/reference API, but Compiler.compile() uses ASTToIR.

Logical and/or retain eager evaluation semantics in version 1: the left operand is evaluated before the right operand and the logical opcode.

## 5. Function Calls and VM Frames

A version 2 bytecode module contains one main chunk and a function table. Each function table entry stores a function name, parameter types, return type, and code chunk. The first arity local slots are reserved for parameters, in declaration order.

The VM uses a shared operand stack and a separate call-frame stack. Each frame owns its code chunk, instruction pointer, local storage, return convention, and operand-stack baseline. CALL removes its arguments from the operand stack, validates them against the function signature, creates a new frame, and transfers control. RETURN restores the caller and pushes a result only for non-void functions.

Function chunks can call any function in the module, including themselves and functions declared later. This supports direct recursion, mutual recursion, and forward references. A configurable call-depth limit prevents unbounded recursion from exhausting the host stack; execution, operand-stack, string-size, and captured-output limits are also enforced.

## 5. Bytecode Versions

- Version 1: Main chunk only; retained as a readable and executable legacy format.
- Version 2: Adds a function table with typed signatures and function chunks, plus CALL and RETURN instructions.

The serializer writes version 2 by default and continues to read version 1. The verifier checks the main chunk and every function chunk independently, including call targets, arity, local slots, jump targets, stack underflow, stack-height merge consistency, return-stack discipline, terminal instructions, source-map coordinates, and structural complexity bounds.

## 6. Optimization

Optimization is layered. The IR pass manager performs scalar constant propagation/folding, constant-branch simplification, unreachable-block removal, copy propagation, dead-code elimination, dominance-aware global common-subexpression elimination, and natural-loop loop-invariant code motion before lowering. A separate side-effect analysis classifies memory reads/writes, observable operations, potentially trapping instructions, and operations safe to speculate. Dead-code elimination removes only unused total/pure operations; loads, calls, array allocation/access/mutation, division, remainder, and other potentially faulting operations remain observable.

Global CSE reuses deterministic expressions only from definitions that dominate all rewritten uses. Local-load reuse is invalidated by a store to the same slot; global loads and mutable collection reads are not commoned. LICM identifies natural loops from dominator back-edges, requires a unique preheader, and hoists only total expressions or local reads proven initialized and unmodified in the loop. Potentially faulting arithmetic and mutable/global reads are not speculated.

IR values may now be used multiple times or in dominated successor blocks. The IR verifier checks same-block definition order and cross-block dominance. IRToBytecode retains the compact stack-only lowering for single-use local values, and selects a materialized-value lowering when required. The latter assigns private local slots to virtual values and uses staged edge copies for block parameters, preserving parallel assignments around loop back-edges. No bytecode opcode or serialized format change is required.

The bytecode optimizer remains a target-specific cleanup pass: conservative instruction folding, typed constant-pool deduplication/compaction, and safe stack-neutral no-op removal. It remaps absolute jump targets and preserves source locations. Compiler(optimize=False) disables both IR and backend transformations; ir_optimize can explicitly isolate the IR pass manager.

## 7. Control-Flow Analysis

Phase 9 adds a read-only control-flow graph (CFG) for the main bytecode chunk and each function chunk. Leaders are the entry instruction, jump targets, and instructions immediately following conditional/unconditional branches or terminators. Each basic block is represented by its first and last instruction offsets; successors encode branch and fall-through edges. A breadth-first traversal from the entry block classifies reachable and unreachable blocks. The analysis does not rewrite bytecode, alter stack behavior, or change the serialized v4 format.

`rifai inspect` exports the CFG under `stages.bytecode.control_flow`, including block ranges, successors, edge counts, and reachable/unreachable instruction totals. This gives compiler tooling and future optimization passes a stable control-flow foundation without coupling analysis to execution.

## 8. Intermediate Representation and Pass Manager

Phase 11 introduced the explicit-value IR model and the compatibility BytecodeToIR lifter. The lifter verifies its input and converts operand-stack entries to typed virtual values; stack merges become target block parameters. This remains useful for inspecting, migrating, and round-tripping verified bytecode modules.

The normal source compiler enters IR through ASTToIR, without generating bytecode first. It uses the semantic analyzer's exact symbol/type bindings and creates typed operations, function signatures, local-slot metadata, constants, and explicit basic blocks directly from the AST. If/else-if statements become conditional edges; while loops become explicit condition/body/exit blocks and back-edges.

IRVerifier checks unique definitions, operation contracts, same-block use order, and cross-block dominance for reachable uses. IRAnalyzer computes reachability, predecessors, dominator sets, immediate dominators, and natural loop back-edges. IRSideEffectAnalysis classifies observable writes, memory reads/writes, potential runtime traps, safe speculation, and deterministic commonable operations.

The pass manager runs deterministic verified passes to a bounded fixed point:
1. Copy propagation for explicit DUP aliases.
2. Scalar constant propagation/folding and constant branch simplification.
3. Unreachable-block elimination.
4. Natural-loop LICM with unique-preheader, stable-local, and speculatability checks.
5. Dominance-aware global CSE with per-slot local-load invalidation.
6. Conservative DCE that retains effectful and potentially trapping operations.
7. Canonical value numbering, final verification, CFG/dominator analysis, and side-effect statistics.

Global CSE and LICM may create a value that is reused across several blocks. IRToBytecode detects these cases and materializes virtual values in private local slots; CFG edge arguments are transferred through scratch slots to preserve parallel-copy semantics. Straight-line, single-use IR continues to use the compact stack lowering. The bytecode verifier validates the final code. Phase 14 output used v4; Phase 15 advances the direct source pipeline to v5 for nominal-type operations while retaining v1–v4 compatibility.

The target-specific BytecodeOptimizer remains after lowering. Compiler(optimize=False) disables both optimization layers while retaining verification and analysis; ir_optimize can isolate the IR pass manager. CompilationResult exposes ir_origin, ir_module, ir_stats, and ir_analysis; rifai inspect exports the same information under its IR stages.

## 9. Diagnostics, Limits, and CLI

Diagnostics identify the phase that emitted them and preserve source line/column coordinates when available. Generated instructions carry source locations into the VM. The VM exposes configurable positive-integer limits for executed instructions, operand-stack depth, call depth, integer bit length, string length, and total captured output. The verifier also bounds local slots per code chunk and constant-string sizes. The serializer caps bytecode files at 16 MiB and writes files using a temporary file plus atomic replacement.

- tokens, parse, ast, and check inspect or validate source.
- compile source.rif [-o output.rbc] [--no-optimize] compiles and saves bytecode.
- run source.rif [--no-optimize] compiles in memory and executes immediately.
- run program.rbc and vm program.rbc execute an existing bytecode module.
- disasm program.rbc validates and displays bytecode.

## 12. Phase 15: Modules, Nominal Types, and Runtime Capabilities

The parser recognizes top-level relative imports, struct declarations, and unit enums. Semantic analysis performs a type-declaration pre-pass before function signature collection, allowing nominal declarations to be referenced from fields, function parameters, return types, constructors, and other imported modules. Local declarations may omit annotations when an initializer determines an exact type.

The compiler resolves imports recursively relative to each importing file and confines every resolved path to the root source directory. Canonical files are visited once; cycles, parent traversal, absolute paths, symlink escapes, missing files, oversized module graphs, and duplicate declarations are rejected. Imported declarations are flattened in dependency-first order into a shared namespace, with token/span offsets remapped into the embedded combined source used by diagnostics and debugging.

Structs lower to STRUCT_NEW, FIELD_GET, and FIELD_SET operations. Struct construction embeds an ordered field schema; the VM stores values in a reference-type StructValue, validates each field assignment against the schema, and traps reads of uninitialized fields. Enums lower to ENUM_NEW, embedding the declared variant list in the instruction; the verifier and VM reject undeclared active variants. Structs are mutable reference values; enums are immutable unit values.

The intrinsic library adds checked numeric, conversion, and string operations. File functions are implemented in the VM but are not automatically available to embedded hosts: the default VM disables file I/O. A host may explicitly grant a file_root capability, and the CLI, interactive debugger, and DAP launch grant only the launched project's directory. Paths are resolved under that root; traversal and symlink escapes are rejected. Reads/writes are bounded UTF-8 text operations, and writes use atomic replacement.

Bytecode v5 added nominal struct/unit-enum instruction contracts and allowed nominal names in function and debugger metadata. Bytecode v6 adds typed enum payload construction and enum pattern-test/payload-extraction instructions. Bytecode v7 adds ARRAY_NEW_TYPED for nested arrays and arrays of nominal values, and recursive type names in signatures/debug metadata. The serializer, verifier, and VM support bytecode versions 1–7; the direct source compiler emits v7. Compatibility APIs continue to lift and lower previously verified bytecode modules without upgrading their format.

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
- Phase 14: Dominance-aware global CSE, copy propagation, conservative dead-code elimination, natural-loop LICM, explicit side-effect/trap analysis, dominance verification, and materialized-value bytecode lowering.

- Phase 15: Relative source imports, nominal structs/enums, inferred local types, standard library expansion, capability-based text I/O, and bytecode v5 with v1–v4 compatibility.
