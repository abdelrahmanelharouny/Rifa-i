# Phase 15 — Language Evolution

## Objective

Extend Rifa'i from primitive/array programs to a small modular language with nominal user-defined data types, safer source imports, better local type inference, and a practical standard library. Preserve v1–v4 bytecode compatibility and make file access an explicit runtime capability.

## Delivered

### Frontend and type system
- Added top-level import, struct, and enum declarations.
- Added postfix dot-member access and field assignment.
- Added optional local type annotations. An unannotated local infers its exact type from the initializer; empty arrays still require an explicit array context.
- Added nominal UserDefinedType metadata for structs and enums.
- Added static checks for duplicate type/field/variant names, field existence, constructor arity/order, exact field types, nominal function parameter/return types, and enum variant membership.
- Structs are mutable reference values; enum values are immutable unit variants. Struct and array equality remain unsupported; enums support same-type equality.

### Source modules
- Added recursive relative .rif imports.
- Imports are resolved relative to the importing file and confined to the root program directory.
- Canonical modules are loaded once, dependency-first. Duplicate declarations share one namespace and are diagnosed; cyclic imports are rejected.
- Added bounds for the module count and combined source size, and retained source locations through a deterministic combined debug source.

### Runtime and standard library
- Added struct construction, field reads/writes, and enum value creation to IR and bytecode.
- Added checked math, conversions, string search/prefix/suffix, substring, and bounded text file functions.
- File I/O is disabled by default in the Python VM API. CLI and debuggers explicitly grant a root-directory capability. Absolute paths, parent traversal, symlink escapes, invalid UTF-8 reads, missing write parents, and oversized files are rejected.
- File writes use temporary files and atomic replacement.
- Added v5-only structural verification and stack effects for nominal operations and intrinsic calls.

### Bytecode compatibility
- Added bytecode v5 with STRUCT_NEW, FIELD_GET, FIELD_SET, and ENUM_NEW.
- v1, v2, v3, and v4 remain accepted by the serializer, verifier, and VM.
- The normal source compiler emits v5. Existing v4 typed arrays and function modules remain valid.

## Language examples

~~~rif
enum State { Ready, Busy }
struct Job { title: string, state: State }

let job = Job("build", State.Ready);
job.state = State.Busy;
print(job.title);
print(job.state == State.Busy);
~~~

For project imports:

~~~rif
import "models/job.rif";
let job = Job("release", State.Ready);
~~~

## Runtime safety boundaries

- The CLI's file access root is the launched source file's directory (or the source directory associated with a bytecode file).
- The Python VM's default remains no file access. Embedding hosts must explicitly enable it and provide file_root.
- The default file limit is 1 MiB per read/write.
- Import graphs are capped at 128 source files and 5 MiB combined source text.
- No dynamic imports, arbitrary Python execution, module aliases, payload enums, pattern matching, structs arrays, or implicit conversions were introduced.

## Validation

The Phase 15 test module covers parser and semantic rules, nominal type execution and aliasing, built-in functions, file capability denial/allowance and path escapes, import ordering/deduplication/cycle/traversal rejection, and bytecode v5 serialization with v4 compatibility. CI also exercises all previous phase examples and developer tooling.

## Version

Rifa'i package version at Phase 15: 0.16.0. Default bytecode format at Phase 15: v5.
