# Rifa'i Language Specification (Version 3.0 — Phase 15)

Rifa'i (.rif) is a statically typed, block-structured language compiled into portable stack bytecode (.rbc) and executed by the Rifa'i VM. Phase 15 adds relative source modules, nominal records and enums, inferred local variables, an expanded standard library, and capability-controlled text file I/O.

## 1. Lexical structure

Source files are UTF-8 .rif files. LF and CRLF line endings are supported. Coordinates are one-based. Whitespace is ignored; // starts a line comment. Identifiers match ASCII letters/underscores followed by ASCII letters, digits, or underscores, and are case-sensitive.

Reserved keywords include import, struct, enum, fn, let, return, if, else, while, print, true, false, int, float, bool, string, void, and, or, and not. Standard-library function names are reserved and cannot be declared as variables, parameters, functions, or nominal types.

Integer literals contain decimal digits; floats have digits on both sides of a decimal point. Double-quoted strings support escaped quote, backslash, newline, tab, and carriage return.

## 2. Types and declarations

Primitive types are int, float, bool, and string. void is valid only as a function return type. Homogeneous one-dimensional arrays are available for primitive element types: int[], float[], bool[], and string[].

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

### Enums

An enum declares a non-empty set of unit variants:

~~~rif
enum Status { Ready, Running, Failed }

let current: Status = Status.Ready;
print(current == Status.Running);
~~~

Variants are constructed using EnumName.Variant. Enum values are immutable and support equality/inequality only against values of the same enum type. Payload variants, pattern matching, and implicit string conversion are not part of this version.

## 3. Modules and imports

A source file may import another source file with:

~~~rif
import "models/user.rif";
~~~

Paths must be relative .rif paths. Parent-directory segments, absolute paths, missing files, symlink escapes, import cycles, more than 128 distinct modules, and combined module text larger than 5 MiB are rejected. Each canonical source file is loaded once per compilation.

Imports are resolved relative to the importing file, but all paths must remain inside the root source file's directory. Imported declarations are flattened in dependency-first order and share one global namespace with the importing file. There are no import aliases or module-qualified symbol namespaces: use the declared type or function name directly. Duplicate declarations across modules are compile-time errors.

Import compilation requires a real source-file path. Calling Compiler.compile() on in-memory text containing imports without a source_name is rejected. The CLI check, compile, run, and debug workflows supply that path.

## 4. Functions, scopes, and control flow

Functions are top-level declarations:

~~~rif
fn increment(value: int) -> int {
    return value + 1;
}
~~~

Function signatures are collected before function bodies, so recursion, mutual recursion, and forward references work across the flattened module set. Function parameter and return types may be primitive, primitive arrays, or declared nominal types. Nested functions and overloading are not supported.

Variables must be declared before use. Duplicate names in one lexical scope are rejected; nested blocks may shadow outer variables. Function parameters share the function body's outermost scope.

if and while conditions must be bool. Top-level return is invalid. A void function may return without a value or fall through; a non-void function must return a matching value on all execution paths.

## 5. Operators

Arithmetic is strict: + accepts matching int, float, or string operands; - and * accept matching numeric operands; / accepts matching numeric operands and returns float; % accepts int only. Mixed int/float arithmetic is not implicit.

Relational operators (<, >, <=, >=) require matching numeric operands. Equality (==, !=) is defined for matching primitive scalar types and matching enum types; it is not defined for structs or arrays. Logical and and or require booleans and eagerly evaluate both operands. Unary - accepts numbers, and not accepts booleans.

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

Arrays are homogeneous, one-dimensional reference values. Non-empty literals infer their element type; empty literals need an explicit type annotation. Indexes are zero-based integers. Reads and writes outside the valid range trap. Arrays can be passed to and returned from functions, and assignments create aliases rather than copies. The VM enforces element types, bounds, and the configurable item-count limit.

## 8. Bytecode compatibility

Bytecode v5 introduces STRUCT_NEW, FIELD_GET, FIELD_SET, and ENUM_NEW, and permits nominal type names in function signatures and debug-local metadata. The serializer and verifier continue to accept versions 1–4. Version 5 is required for nominal-type instructions and the new intrinsic CALL targets. Existing array operations remain supported in v5.

## 9. Evaluation order and runtime limits

Operands are evaluated eagerly from left to right. Logical and/or are not short-circuiting in this version. The VM enforces configurable limits on executed instructions, stack depth, call depth, local-frame size, integer bit length, string length, array items, output size, and file bytes. Malformed bytecode is verified before execution.
