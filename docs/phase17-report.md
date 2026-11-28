# Phase 17 — Algebraic Data Types & Pattern Matching

## Delivered

- Enum declarations now support unit cases and typed positional payloads, for example `enum Result { Ok(int), Error(string), Empty }`.
- Enum payload constructors validate variant existence, exact argument count, and each payload's static type.
- Enum runtime values are immutable tagged values carrying an ordered payload tuple.
- Added expression-level `match` with enum-qualified patterns, arm-local payload bindings, wildcard fallback, and exhaustive coverage validation.
- All non-void match arms must produce the same static type. Duplicate patterns, wrong enum names, unknown variants, payload binding errors, early wildcards, and non-exhaustive matches are rejected during semantic analysis.
- Lowered enum construction and matching through typed IR operations and explicit conditional CFG blocks; the subject is evaluated once.
- Added bytecode v6 operations `ENUM_NEW_PAYLOAD`, `ENUM_IS`, and `ENUM_GET`, with bounded operand schemas, runtime tag/type checks, and version gates.
- Integrated the new operations with IR verification, BytecodeToIR, IRToBytecode, optimizer effect classification, bytecode data-flow stack transfer, and debugger local metadata.
- Kept bytecode v1-v5 readable and executable. The new algebraic-enum opcodes require v6.

## Example

~~~rif
enum Result { Ok(int), Error(string), Empty }

let message: string = match (Result.Ok(42)) {
    Result.Ok(value) => "value=" + to_string(value),
    Result.Error(reason) => "error=" + reason,
    Result.Empty => "empty",
};
~~~

## Validation

Phase 17 tests run with optimization both enabled and disabled. They cover enum parsing, typed constructors, payload formatting, scoped pattern bindings, nested nominal payloads, nested match expressions, wildcard handling, exhaustiveness and other semantic errors, bytecode v6 serialization, IR verification/lifting/lowering, and v5 compatibility.

## Compatibility

Default bytecode format: v6. Package version: 0.18.0. Versions 1 through 5 remain supported; only the three new algebraic-enum instructions are gated to v6.
