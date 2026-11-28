# Rifa'i Language Specification (Version 4.0 — Phase 19)

Rifa'i (.rif) is a statically typed, block-structured language compiled into portable stack bytecode (.rbc) and executed by the Rifa'i VM. The language includes relative source modules, nominal records and algebraic enums, exhaustive matching, inferred local variables, bounded generics, generic structs and enums, recursive homogeneous arrays, and capability-controlled text file I/O.

## 1. Lexical structure

Source files are UTF-8 .rif files. LF and CRLF line endings are supported. Coordinates are one-based. Whitespace is ignored; // starts a line comment. Identifiers match ASCII letters/underscores followed by ASCII letters, digits, or underscores, and are case-sensitive.

Reserved keywords include import, struct, enum, fn, let, return, if, else, while, for, break, continue, match, print, true, false, int, float, bool, string, void, and, or, and not. Standard-library function names are reserved and cannot be declared as variables, parameters, functions, or nominal types.

Integer literals contain decimal digits; floats have digits on both sides of a decimal point. Double-quoted strings support escaped quote, backslash, newline, tab, and carriage return.

## 2. Types and declarations

Primitive types are int, float, bool, and string. void is valid only as a function return type. A concrete value type may be a primitive, a declared struct, a declared enum, or an array of another concrete value type. Homogeneous arrays support any such non-void element type and may be nested: int[], Point[], Box<int>[], int[][], and Box<string>[][] are valid examples.

Local declarations may be explicitly annotated or inferred from a non-void initializer:

~~~rif
let count: int = 3;
let greeting = "Hello";
let scores = [10, 20, 30];
~~~

Inference is exact; there are no implicit numeric conversions. Empty array literals still need a declared array type, because an unannotated empty array has no element type to infer. void expressions cannot initialize variables.

### Structs

A struct declares a nominal record with a non-empty, ordered set of fields:

~~~rif
struct User {
    name: string,
    age: int
}

let user = User("Ada", 36);
print(user.name);
user.age = user.age + 1;
~~~

Construction is positional and must supply exactly one argument per field in declaration order. Every value is checked against its declared field type. Fields can be read with value.field and assigned with value.field = expression;. Unknown fields and mismatched field assignments are static errors.

Structs are reference values: assignment and parameter passing copy the reference, not the record. Updating a field through one alias is visible through other aliases. Struct equality is not defined; compare individual fields explicitly. Nested struct fields and primitive array fields are allowed.

### Algebraic enums

An enum declares a non-empty set of uniquely named variants. Each variant may be a unit case or carry an ordered tuple of typed payload values:

~~~rif
enum Status { Ready, Running, Failed }
enum Result { Ok(int), Error(string), Pair(int, string), Empty }

let current: Status = Status.Ready;
let answer: Result = Result.Ok(42);
let failure = Result.Error("offline");
~~~

Unit variants use `EnumName.Variant`; payload variants use `EnumName.Variant(value, ...)`. Payload arity and each payload type are checked statically. Enum values are immutable tagged values whose payload tuple follows declaration order. Assignment and function calls preserve the enum value. Equality/inequality is supported only between values of the same enum type.

### Exhaustive pattern matching

The `match` expression selects an arm using the active enum variant. Patterns name the enum and variant, and may bind each payload position to a new arm-local variable. A final wildcard `_` covers any remaining cases:

~~~rif
fn describe(result: Result) -> string {
    return match (result) {
        Result.Ok(value) => "value=" + to_string(value),
        Result.Error(message) => "error=" + message,
        Result.Pair(value, label) => label + to_string(value),
        Result.Empty => "empty",
    };
}

let summary = match (Result.Ok(7)) {
    Result.Ok(value) => to_string(value),
    _ => "not successful",
};
~~~

Every declared variant must appear exactly once unless a final wildcard arm is present. Duplicate arms, a wildcard before the final arm, mismatched enum names, unknown variants, incorrect payload binding counts, and arm result-type mismatches are compile-time errors. All arms must return the same non-void type. Payload bindings exist only inside their arm. Matching a non-enum value is rejected. Match expressions can be nested and used in declarations, returns, arguments, and other expressions.

## 3. Modules and imports

A source file may import another source file with:

~~~rif
import "models/user.rif";
~~~

Paths must be relative .rif paths. Parent-directory segments, absolute paths, missing files, symlink escapes, import cycles, more than 128 distinct modules, and combined module text larger than 5 MiB are rejected. Each canonical source file is loaded once per compilation.

Imports are resolved relative to the importing file, but all paths must remain inside the root source file's directory. Imported declarations are flattened in dependency-first order and share one global namespace with the importing file. There are no import aliases or module-qualified symbol namespaces: use the declared type or function name directly. Duplicate declarations across modules are compile-time errors.

Import compilation requires a real source-file path. Calling Compiler.compile() on in-memory text containing imports without a source_name is rejected. The CLI check, compile, run, and debug workflows supply that path.

## 4. Functions, scopes, and control flow

### Generic functions, explicit type arguments, and bounds

Functions may declare one or more type parameters. A type parameter can have one or more built-in capability bounds, joined with `+`:

~~~rif
fn identity<T>(value: T) -> T {
    return value;
}

fn add<T: Addable>(left: T, right: T) -> T {
    return left + right;
}

fn first<T: ArrayElement>(items: T[]) -> T {
    return items[0];
}

let number = identity(42);          // inferred type argument
let greeting = identity<string>("hello"); // explicit type argument
let total = add(4, 5);
let head = first([10, 20, 30]);
~~~

Type arguments are normally inferred by unifying the declared parameter types with actual argument types. Multiple parameters using the same type variable must agree. Explicit type arguments are accepted at call sites as `function<T, U>(...)`; they are useful when an argument does not provide enough information, such as an empty array. Every type argument must resolve to a known, non-void concrete type. Generic parameters still need to appear in a parameter type, so type variables that cannot be inferred from a call are rejected at declaration time.

The supported built-in bounds are:

| Bound | Types that satisfy it |
|---|---|
| `Numeric` | `int`, `float` |
| `Integral` | `int` |
| `Addable` | `int`, `float`, `string` |
| `Comparable`, `Ordered` | `int`, `float` |
| `Equatable` | `int`, `float`, `bool`, `string`, enums |
| `Display`, `Printable` | Any concrete non-void value type |
| `ArrayElement` | Any concrete non-void value type |
| `Copy` | Primitive scalar types and enums |

For example, `T: Numeric + Comparable` requires the type argument to satisfy both capabilities. Unknown bounds and unsatisfied constraints are compile-time errors. Bounds are checked before each concrete specialization; the ordinary semantic analyzer then checks every operation in the specialized body. The built-in capability set is fixed in this version; user-declared traits and implementations are not supported.

### Generic structs and enums

Structs and enums may declare type parameters with the same bound syntax:

~~~rif
struct Box<T: Display> {
    value: T,
}

enum Option<T: Display> {
    Some(T),
    None,
}

let inferred = Box(42);                    // infer T = int
let explicit: Box<string> = Box<string>("hello");
let some: Option<int> = Option<int>.Some(7);
let none: Option<string> = Option<string>.None;
~~~

Struct constructor arguments and enum payloads can infer type arguments. Explicit type arguments are required for generic unit variants because they carry no payload from which to infer the type. Generic nominal types can appear inside other generic types, function signatures, arrays, and nested arrays. Each concrete type-argument tuple produces one deterministic nominal declaration that the rest of the compiler treats as an ordinary struct or enum. Generic declarations themselves are removed before semantic analysis.

### Monomorphization

Generic functions and nominal types are specialized at compile time before ordinary semantic analysis. Specializations are deterministic and cached by their concrete type arguments, including recursive and nested generic references. The generated declarations are checked using the normal static type rules and then lowered through the regular IR and bytecode pipeline. Generic runtime dispatch, erased type representations, and runtime type-argument metadata are not used.

Functions are top-level declarations:

~~~rif
fn increment(value: int) -> int {
    return value + 1;
}
~~~

Function signatures are collected before function bodies, so recursion, mutual recursion, and forward references work across the flattened module set. Function parameter and return types may be primitive, primitive arrays, or declared nominal types. Nested functions and overloading are not supported.

Variables must be declared before use. Duplicate names in one lexical scope are rejected; nested blocks may shadow outer variables. Function parameters share the function body's outermost scope.

if, while, and present for-loop conditions must be bool. A for loop uses C-style clauses: for (initializer; condition; increment) { ... }. Each clause is optional; an omitted condition is treated as true. The initializer may be a let declaration, assignment, or expression statement. A variable declared in the initializer is visible in the condition, increment, and body, but not after the loop. break and continue are allowed only inside loops and always target the innermost enclosing loop. In a for loop, continue executes the increment clause before checking the condition again. Top-level return is invalid. A void function may return without a value or fall through; a non-void function must return a matching value on all execution paths.

## 5. Operators

Arithmetic is strict: + accepts matching int, float, or string operands; - and * accept matching numeric operands; / accepts matching numeric operands and returns float; % accepts int only. Mixed int/float arithmetic is not implicit.

Relational operators (<, >, <=, >=) require matching numeric operands. Equality (==, !=) is defined for matching primitive scalar types and matching enum types; it is not defined for structs or arrays. Logical and and or require booleans and use short-circuit evaluation: and skips its right operand when the left operand is false, while or skips its right operand when the left operand is true. Unary - accepts numbers, and not accepts booleans.

Precedence, from highest to lowest: primary and postfix access; unary; multiplication/division/modulo; addition/subtraction; relational comparison; equality; logical AND; logical OR. Binary operators are left-associative; unary operators are right-associative.

## 6. Standard library

All standard-library functions are statically checked and have runtime argument validation.

| Function | Signature | Behavior |
|---|---|---|
| len | len(string or T[]) -> int | String character or array element count |
| push | push(T[], T) -> void | Append a matching typed array element |
| pop | pop(T[]) -> T | Remove and return the last element; empty arrays trap |
| abs | abs(int or float) -> same type | Absolute value |
| min, max | Two matching numeric values -> same type | Minimum or maximum |
| sqrt | sqrt(int or float) -> float | Square root |
| round | round(int or float) -> int | Python-compatible nearest-integer rounding |
| to_int | to_int(int or float) -> int | Numeric conversion, truncating floats toward zero |
| to_float | to_float(int or float) -> float | Numeric conversion |
| to_string | to_string(value) -> string | Render a supported runtime value |
| contains | contains(string, string) -> bool | Substring membership |
| starts_with | starts_with(string, string) -> bool | Prefix check |
| ends_with | ends_with(string, string) -> bool | Suffix check |
| substring | substring(string, int, int) -> string | Start-inclusive, end-exclusive indexes |
| read_text | read_text(relative_path) -> string | Read bounded UTF-8 text |
| write_text | write_text(relative_path, string) -> bool | Atomically replace a bounded UTF-8 text file |
| file_exists | file_exists(relative_path) -> bool | Test whether a regular file exists |

Runtime errors are raised for invalid numeric operations, out-of-range substring indexes, empty array pops, non-finite floating-point results, and resource-limit violations.

### File I/O capabilities

File I/O is disabled by default for Python-created VirtualMachine instances. A host must explicitly construct the VM with allow_file_io=True and a file_root. Reads and writes are confined to that resolved directory; absolute paths, parent-directory traversal, symlink escapes, missing write parents, invalid UTF-8 reads, and files larger than max_file_bytes are rejected. The default per-file limit is 1 MiB. Writes use a temporary file in the destination directory and atomic replacement.

The CLI and debuggers grant this capability only within the launched program's project directory. Compiled bytecode does not bypass the VM's file capability settings.

## 7. Arrays

Arrays are homogeneous, mutable reference values. A non-empty literal infers the common element type; all elements must match exactly. Empty literals need an explicit surrounding array type, such as `let rows: int[][] = [[], []];`. Indexes are zero-based integers. Reads and writes outside the valid range trap. Arrays can be passed to and returned from functions, and assignment creates aliases rather than copies. The VM enforces element types recursively, bounds, and the configurable item-count limit.

Array element types may be primitive values, structs, enums, or other arrays. Examples include `Point[]`, `Box<int>[]`, `int[][]`, and `Option<string>[][]`. The built-ins `len`, `push`, and `pop` work with arrays at any supported nesting level; `push` requires an element matching the array's immediate element type.

## 8. Bytecode compatibility

Generic functions, structs, and enums are specialized into ordinary concrete declarations before IR generation. Type constraints are compile-time checks and add no runtime dispatch. Primitive one-dimensional arrays continue to use their existing typed constructor opcodes. Bytecode v7 adds `ARRAY_NEW_TYPED` for nested arrays and arrays containing nominal values, and expands valid function/debug type names to recursive array types.

Bytecode v5 introduced `STRUCT_NEW`, `FIELD_GET`, `FIELD_SET`, and unit `ENUM_NEW`. Bytecode v6 adds `ENUM_NEW_PAYLOAD`, `ENUM_IS`, and `ENUM_GET` for algebraic enum construction and matching. Bytecode v7 adds generic typed-array construction. The serializer and verifier accept versions 1–7; versions 1–6 remain readable and executable. `ARRAY_NEW_TYPED` is rejected in versions 1–6. The compiler emits v7 modules by default.

## 9. Evaluation order and runtime limits

Ordinary binary operands are evaluated eagerly from left to right. Logical and/or conditionally evaluate the right operand using compiler-generated control flow. The VM enforces configurable limits on executed instructions, stack depth, call depth, local-frame size, integer bit length, string length, array items, output size, and file bytes. Malformed bytecode is verified before execution.
