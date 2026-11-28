# Phase 18 — Generics & Parametric Polymorphism

## Delivery

Phase 18 introduces generic function declarations and compile-time type inference through monomorphization. A function may declare one or more type parameters after its name:

```rif
fn identity<T>(value: T) -> T {
    return value;
}

fn first<T>(items: T[]) -> T {
    return items[0];
}

let answer = identity(42);
let label = identity("Rifa'i");
let head = first([10, 20, 30]);
```

## Compiler design

The parser records generic type parameters on the immutable function AST and accepts type-variable array annotations such as `T[]`. Before semantic analysis, `GenericSpecializer` infers the concrete types at each call site and creates a deterministic concrete function instance.

Specializations are cached by the generic function and ordered type tuple. The cache entry is established before recursively processing the body, allowing generic recursion and calls between generic functions. The specializer substitutes type variables in parameter, return, and local annotations and rewrites calls to generated function symbols.

Every generated instance is processed by the existing semantic analyzer, typed IR pipeline, bytecode verifier, and VM. Generic functions therefore add no bytecode operations, runtime dispatch, or serialized format changes. Generic behavior is resolved at compile time.

## Supported in this phase

- Multiple function type parameters, inferred from argument types.
- One type parameter reused across multiple parameters, requiring consistent concrete types.
- Primitive values and nominal struct/enum values as type arguments.
- One-dimensional primitive arrays through annotations such as `T[]`.
- Deterministic specialization caching, nested generic calls, and recursive generic functions.
- Normal semantic validation of each concrete generic function body.
- Language Server diagnostics, hover/signature information, and source-level names for generated specializations.
- VS Code generic-function snippet and syntax scopes.

## Deliberate boundaries

- Generic structs and generic enums are not introduced.
- Explicit type arguments at call sites are not required or supported; inference is from call arguments.
- Type bounds/constraints and associated types are not introduced. Operators are checked after specialization, for every concrete type.
- Empty array literals do not carry enough information to infer an element type.
- Nested arrays and arrays whose element type is a user-defined nominal type remain unsupported by the language's current collection model.
- A type variable must occur in at least one parameter annotation so its value can be inferred.

## Compatibility

The generic pass emits ordinary function declarations before IR generation. Bytecode v6 and all existing older-format compatibility behavior remain unchanged; no VM or serializer changes are needed.

## Validation

The Phase 18 regression suite exercises optimized and unoptimized execution, primitive and nominal specializations, array parameters, repeated/cached instantiations, nested generic calls, recursion, invalid/conflicting inference, empty-array inference failures, and concrete body type checking. The existing compiler, VM, IR, debugger, and LSP suites remain part of the repository-wide CI workflow.
