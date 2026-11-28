# Phase 13 Report — Direct AST-to-IR Compilation

## Objective

Make the typed IR the normal compiler's first intermediate representation. Source compilation must no longer generate stack bytecode and then lift that bytecode back into IR before optimization.

## Delivered

- Added ASTToIR, a direct lowering pass over the semantically validated Program AST.
- Reused the semantic analyzer's identity-keyed variable/function bindings and expression types; the IR builder does not redo name lookup or infer source types.
- Added direct lowering for literals, scalar operators, variable loads/stores, function calls and returns, print statements, typed array construction/indexing/mutation, len/push/pop, blocks, if/else-if, and while loops.
- Created typed IR virtual values and explicit operation inputs/outputs.
- Created explicit branch/jump/return/halt terminators and deterministic basic-block layout.
- Kept expression temporaries local to each block. Local/global storage represents source variables across control-flow boundaries, avoiding implicit cross-block temporary uses.
- Preserved source locations on operations and terminators, embedded original source text, and emitted per-function local-symbol tables for debugger views.
- Added IRPipeline.run_ast() and made Compiler.compile() use the direct source-AST route.
- Kept BytecodeToIR as a compatibility API for already-verified bytecode, migration, inspection, and round-trip workflows.
- Kept the existing v4 stack-bytecode backend, serializer, VM, and target-specific bytecode cleanup pass unchanged.
- Exposed the IR origin in CompilationResult and rifai inspect.
- Added a runnable end-to-end example and dedicated direct-lowering tests.

## Pipeline

The normal source path is now:

    .rif source
      -> Lexer
      -> Parser
      -> Semantic Analyzer
      -> ASTToIR
      -> IR verifier / pass manager / analysis
      -> IRToBytecode
      -> target-specific BytecodeOptimizer (when enabled)
      -> BytecodeVerifier
      -> .rbc / VM

BytecodeToIR remains available as a separate compatibility entry point; it is not called by Compiler.compile().

## Control Flow and Value Semantics

- If/else-if statements lower to explicit true/false edges and join blocks.
- While loops lower to condition, body, and exit blocks with explicit back-edges.
- Expressions are evaluated in source order and produce typed virtual values.
- Variables use local/global loads and stores. All current statement forms leave no transient expression values on a control-flow edge.
- Void calls and mutating collection operations correctly produce no result value.
- Function signatures, recursion, mutual recursion, arrays, nested lexical scopes, and shadowed locals retain semantic bindings.
- Source locations stay attached to executable instructions after lowering.

## Compatibility

- No bytecode opcode or .rbc format change; output remains bytecode v4.
- Existing v1-v4 modules remain supported by the serializer, verifier, and VM.
- BytecodeToIR and IRToBytecode remain public APIs.
- The old AST-to-bytecode CodeGenerator remains available as a reference/compatibility API, but is no longer used by Compiler.compile().
- Debugger/LSP/CLI continue to consume the same bytecode and embedded debug metadata contracts.

## Validation

The Phase 13 suite covers:
- direct AST-to-IR construction and IR verification;
- arrays, indexing, mutation, push/pop/len, functions, mutual recursion, branches, loops, and nested-scope shadowing;
- source text, source maps, and local-symbol metadata;
- bytecode lowering and VM output parity;
- compiler-path isolation proving Compiler.compile() does not call CodeGenerator.generate();
- structured inspection reporting origin=direct-ast.

The CI workflow also executes and inspects examples/phase13_direct_ast_to_ir.rif.
