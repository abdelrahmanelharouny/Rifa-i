# Rifa'i Compiler Architecture

This document describes the modular architecture of the **Rifa'i Compiler** and **Rifa'i VM**.

## 1. Pipeline Overview

~~~text
  [.rif source file]
          |
          v
  +-------------------+
  | Frontend: Lexer   |  Phase 1
  +---------+---------+
            | LexResult(tokens, diagnostics)
            v
  +-------------------+
  | Frontend: Parser  |  Phase 2
  +---------+---------+
            | ParseResult(program, diagnostics)
            v
  +-------------------+
  | Semantic Analyzer |  Phase 2
  +---------+---------+
            | SemanticResult(diagnostics, inferred types, bindings)
            v
  +-------------------+
  | Bytecode Generator|  Phase 4
  +---------+---------+
            | BytecodeModule
            v
  +-------------------+
  | Bytecode Serializer| Phase 3
  +---------+---------+
            | .rbc
            v
  +-------------------+
  | Rifa'i VM         |  Phase 3 core / Phase 4 functions
  +-------------------+
~~~

Phase 3 establishes a usable bytecode contract and VM core. It deliberately does not compile source AST nodes; AST-to-bytecode generation is Phase 4.

## 2. Package Layout

- rifai/cli.py and rifai/__main__.py: CLI entrypoint.
- rifai/errors/diagnostics.py: shared source-aware diagnostics.
- rifai/frontend/: Lexer, Parser, AST, type system, scopes, and semantic model.
- rifai/bytecode/instructions.py: opcode definitions, operands, source locations, and stack effects.
- rifai/bytecode/chunk.py: immutable code chunk structure.
- rifai/bytecode/module.py: module and constant-pool model.
- rifai/bytecode/verifier.py: structural, operand, CFG, and stack-height validation.
- rifai/bytecode/serializer.py: versioned .rbc encoding and decoding.
- rifai/bytecode/disassembler.py: readable instruction listing.
- rifai/vm/machine.py: stack-based interpreter.
- rifai/vm/runtime.py: execution results and runtime exceptions.

## 3. Bytecode Model

A BytecodeModule contains:
- A typed constant pool (int, float, bool, and string).
- One main CodeChunk.
- A source-name field.
- A bytecode format version.

A CodeChunk contains:
- A stable name.
- An immutable instruction tuple.
- A local-slot count.
- An arity field reserved for future function chunks.

Every instruction contains an Opcode, an optional typed operand, and an optional source location.

Version 1 is intentionally a single-main-chunk format. Function chunks and call-frame execution are introduced in Phase 4.

## 4. Instruction and Stack Conventions

The VM is stack-based. Constant and load instructions push one value. Store, print, and pop instructions consume one value. Binary operators consume two values and push one result. Unary operators preserve stack height. DUP duplicates the top item. JUMP transfers to an absolute instruction index. JUMP_IF_FALSE consumes a boolean and branches when it is false. HALT terminates the main chunk and requires an empty operand stack.

LOAD_LOCAL and STORE_LOCAL address zero-based slots in the active chunk. LOAD_GLOBAL and STORE_GLOBAL use a global symbol name. Local slots begin uninitialized; reading an uninitialized slot is a runtime error.

The VM enforces exact runtime operand types to mirror the frontend's strict static type rules. Integer division produces a float. String addition concatenates strings. Division and modulo by zero produce source-aware runtime diagnostics.

## 5. Verification and Serialization

The .rbc file begins with the RIFAI-RBC magic header and contains a UTF-8 JSON payload with format version 1. Constants are tagged with explicit types so JSON booleans and integers cannot be confused.

The verifier runs before execution and validates:
- Supported format version and constant values.
- Opcode and operand contracts.
- Constant and local indices.
- Jump target ranges.
- Exactly one final HALT.
- Operand-stack underflow.
- Consistent stack heights at control-flow merge points.
- No reachable fall-through beyond the instruction sequence.
- An empty operand stack at HALT.

The verifier is not a replacement for runtime checks. Dynamic values, uninitialized locals, undefined globals, invalid operand types, division by zero, and instruction/stack resource limits are checked by the VM.

## 6. Diagnostics and Runtime Behavior

Bytecode verification uses the shared BYTECODE diagnostic phase. Runtime failures use VM diagnostics. Instructions may carry source-map locations so faults can point back to the source line and column once Phase 4 emits instructions from AST nodes.

The VM captures print output in ExecutionResult.output, returns a read-only snapshot of globals, and exposes instruction counts and the final stack for testing and embedding. The CLI is responsible for writing captured output to the terminal.

## 7. Phase Boundaries

- **Phase 1:** Language specification foundation and Lexer.
- **Phase 2:** AST, Parser, Symbol Table, and Semantic Analyzer.
- **Phase 3:** Bytecode model, serializer, verifier, disassembler, and basic VM.
- **Phase 4:** AST-to-bytecode code generation, function chunks, call frames, and full source execution.
- **Phase 5:** Optimization, full-pipeline hardening, tests, and final documentation.
