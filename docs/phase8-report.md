# Phase 8 — Typed Collections

## Delivery overview

Phase 8 adds statically typed homogeneous arrays and a small standard collection API to Rifa'i. The implementation spans lexing, parsing, AST, semantic analysis, bytecode generation, v4 serialization/verification, the VM, LSP completions, debugger display, tests, and examples.

## Language surface

Supported array types are `int[]`, `float[]`, `bool[]`, and `string[]`.

~~~rif
let scores: int[] = [8, 9, 10];
let names: string[] = [];
scores[1] = 12;
push(scores, 11);
print(scores[0]);
print(pop(scores));
print(len(names));
~~~

Non-empty literals infer the element type and require exact homogeneity. Empty literals are supported when a surrounding declaration, parameter, or return type provides the array type. Nested arrays and implicit element conversions are not supported.

Arrays can be passed to and returned from functions. They are reference values, so aliases observe mutations. Array indexing is zero-based.

## Standard collection functions

| Function | Signature | Behavior |
|---|---|---|
| `len` | `len(string) -> int` / `len(T[]) -> int` | String character count or array element count |
| `push` | `push(T[], T) -> void` | Append an element matching the declared element type |
| `pop` | `pop(T[]) -> T` | Remove and return the final element |

The identifiers `len`, `push`, and `pop` are reserved for the standard library; they cannot be declared as variables, parameters, or user functions.

## Bytecode v4

Version 4 adds:
- Typed construction instructions: `ARRAY_NEW_INT`, `ARRAY_NEW_FLOAT`, `ARRAY_NEW_BOOL`, `ARRAY_NEW_STRING`.
- Indexed read and mutation: `ARRAY_GET`, `ARRAY_SET`.
- Collection built-ins: `LENGTH`, `ARRAY_PUSH`, `ARRAY_POP`.

The verifier models exact operand-stack effects, validates construction counts, and rejects collection opcodes in v1/v2/v3 modules. Versions 1, 2, and 3 remain readable and executable. Debug metadata introduced in v3 remains supported in v4.

## Runtime safety

The VM enforces:
- Exact primitive element types during construction, assignment, push, parameter passing, and function return.
- Zero-based index bounds on reads and writes.
- An explicit runtime error when popping an empty array.
- A configurable `max_array_items` limit on construction, push, and initial host-provided globals.
- Existing instruction, stack, call-depth, integer, string, and output resource limits.

Arrays are not serialized as host-language objects in the constant pool; compiled v4 modules construct them through verified bytecode instructions. Their source/type debug metadata is serialized as usual.

## Editor and developer experience

The Language Server completion catalog includes array annotations and standard collection function names. CLI debugger and DAP variable display show arrays using the Rifa'i value representation. The example `examples/phase8_collections.rif` exercises all four element types, function parameters/returns, indexing, mutation, aliases, and collection operations.

## Validation

Automated tests cover:
- Lexing and parsing brackets, typed annotations, literals, indexing, and index assignment.
- Homogeneous element checking, empty-array type context, array parameter/return checking, and builtin signatures.
- VM array construction, aliasing, indexing, mutation, push/pop/length, bounds, capacity limits, and runtime element checks.
- v4 serialization round trips, v1/v2/v3 compatibility, and verifier rejection of collection opcodes in older format versions.
- CLI execution/compilation, Language Server completion catalogs, and debugger array formatting.
