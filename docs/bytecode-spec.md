# Rifa'i Bytecode Specification

## 1. Container Format

The bytecode file begins with the ASCII magic header `RIFAI-RBC` followed by a newline, then a UTF-8 JSON payload.

### Version 1

Version 1 contains exactly:
- `magic`: `RIFAI`
- `format_version`: integer 1
- `source_name`: string or null
- `constants`: typed constant array
- `main`: main code chunk

### Version 2

Version 2 contains all version 1 fields plus:
- `functions`: array of function records.

A function record contains:
- `name`: unique non-empty function name
- `parameter_types`: ordered array of supported value types
- `return_type`: one of supported value types or void
- `chunk`: executable code chunk

### Version 3

Version 3 contains all version 2 fields plus:
- `debug_info`: an object or null.

The `debug_info` object contains:
- `source_text`: original UTF-8 source text or null.
- `local_symbols`: an array of per-chunk records. Each record has `chunk` (the main/function chunk name) and `locals`. Each local entry stores `slot` (zero-based local slot), `name` (source identifier), and `type` (static language type).

Debug metadata is optional for hand-authored bytecode, but compiler-produced source programs embed it by default. Embedded source text is limited to 8 Mi characters and the complete bytecode file is limited to 16 MiB. The verifier rejects unknown chunks, duplicate chunk entries, duplicate slots, invalid names/types, and slots outside their owning chunk. Metadata is informational and does not affect VM execution semantics.

The serializer writes version 6 by default and retains v1-v5 read/write compatibility. Version 4 adds typed-array instructions; version 5 adds nominal structs, unit enums, and intrinsic standard-library CALL targets; version 6 adds typed enum payload construction and pattern matching. The reader and verifier accept versions 1 through 6. Constants are tagged as int, float, bool, or string; non-finite floats are forbidden. JSON keys must be unique.

## 2. Code Chunks and Frames

A code chunk contains:
- `name`: non-empty name (`<main>` for the main program)
- `arity`: non-negative integer
- `local_count`: number of local slots
- `instructions`: ordered instruction array

For a function chunk, arity must equal the length of its parameter signature and local_count must be at least arity. The first arity slots hold parameters in declaration order. Other locals use the remaining zero-based slots.

Version 1 modules contain only the main chunk. Version 2–6 modules contain one main chunk and zero or more function chunks.

## 3. Instruction Encoding

Each instruction contains:
- `opcode`: exact opcode name
- `operand`: integer, string, or null according to the opcode contract
- `location`: optional source location (line, column, start_offset, end_offset)

Jump targets are absolute, zero-based instruction indices within the current chunk.

| Opcode | Operand | Stack effect | Behavior |
|---|---|---:|---|
| CONSTANT | constant index | +1 | Push a constant-pool value |
| POP | none | -1 | Discard the top value |
| DUP | none | +1 | Duplicate the top value |
| LOAD_LOCAL | local slot | +1 | Push an initialized local |
| STORE_LOCAL | local slot | -1 | Store and pop into a local |
| LOAD_GLOBAL | symbol name | +1 | Push an existing global |
| STORE_GLOBAL | symbol name | -1 | Store and pop into a global |
| NEGATE | none | 0 | Numeric unary negation |
| NOT | none | 0 | Boolean negation |
| ADD | none | -1 | Numeric addition or string concatenation |
| SUBTRACT | none | -1 | Numeric subtraction |
| MULTIPLY | none | -1 | Numeric multiplication |
| DIVIDE | none | -1 | Numeric division, result is float |
| MODULO | none | -1 | Integer remainder |
| EQUAL / NOT_EQUAL | none | -1 | Strict same-type equality/inequality |
| LESS / LESS_EQUAL | none | -1 | Numeric less-than comparisons |
| GREATER / GREATER_EQUAL | none | -1 | Numeric greater-than comparisons |
| AND / OR | none | -1 | Boolean conjunction/disjunction; source-level operators lower to short-circuit branches |
| PRINT | none | -1 | Consume and capture a printable value |
| JUMP | instruction index | 0 | Unconditional branch |
| JUMP_IF_FALSE | instruction index | -1 | Pop bool and branch when false |
| CALL | function name | -arity + returns-value | Invoke a function with arguments already on the stack |
| RETURN | none | function terminal | Return the top value from value functions; void functions return no value |
| ARRAY_NEW_INT / ARRAY_NEW_FLOAT / ARRAY_NEW_BOOL / ARRAY_NEW_STRING | element count | 1 - count | Pop count homogeneous primitive values and create a typed array |\n| ARRAY_GET | none | -1 | Pop an integer index and array; push the indexed element |\n| ARRAY_SET | none | -3 | Pop value, index, and array; mutate one element |\n| LENGTH | none | 0 | Replace a string or array with its length |\n| ARRAY_PUSH | none | -2 | Pop value and array; append the typed value |\n| ARRAY_POP | none | 0 | Pop an array and push its final element |\n| HALT | none | 0 | End the main chunk |

+1 means a value is added to the stack; -1 means a value is removed; 0 means stack height is unchanged. CALL consumes exactly the callee's arity. It pushes one result for non-void functions and no result for void functions. RETURN is valid only in function chunks; HALT is valid only in the main chunk.

### Version 5 Nominal-Type Instructions

Version 5 adds the following instructions:

| Opcode | Operand | Stack effect | Behavior |
|---|---|---:|---|
| STRUCT_NEW | schema string | +1 | Allocate a nominal struct with a checked field schema |
| FIELD_GET | field identifier | 0 | Pop a struct reference and push its initialized field |
| FIELD_SET | field identifier | -2 | Pop value and struct reference, validate the field type, and mutate the field |
| ENUM_NEW | enum schema string | +1 | Construct one declared immutable unit variant |

The STRUCT_NEW operand uses TypeName|field:type,field:type encoding. FIELD_GET and FIELD_SET carry only the field identifier. ENUM_NEW uses EnumName|VariantA,VariantB|SelectedVariant; the verifier checks that the active variant is present in the schema.

Version 5 function parameter/return signatures and debug-local metadata may use nominal type names in addition to primitive and primitive-array types. The new intrinsic CALL targets include math, numeric conversion, string, and file helpers. User-defined function names cannot collide with standard-library names.

STRUCT_NEW, FIELD_GET, FIELD_SET, ENUM_NEW, and the new intrinsic CALL targets are invalid in versions 1–4. Existing v1–v4 bytecode remains readable and executable.

## 4. Verification Invariants

The verifier validates the main chunk and every function chunk:
- Supported bytecode version and typed constants.
- Version-gated nominal instruction contracts and schema encodings.
- Unique function names and supported function signatures.
- Function arity and local-slot layout.
- Opcode/operand contracts and known call targets.
- Constant indices, local slots, and jump targets.
- Exactly one final HALT in the main chunk.
- No HALT in function chunks and no RETURN in the main chunk.
- Correct operand-stack depth at RETURN (zero for void, one for value returns).
- No reachable stack underflow or inconsistent stack depth at control-flow merge points.
- No reachable instruction path falling beyond the end of its chunk.
- An empty operand stack at main HALT.
- Valid source-map types and coordinates.
- For v3, valid debug-metadata structure and chunk/slot references.
- Structural caps on constant count, function count, instruction count, local slots, and constant-string size.

Runtime checks remain necessary for dynamic value types, uninitialized locals, undefined globals, zero division, finite floating-point results, and execution/stack/call-depth, integer-size, string-size, and captured-output limits.

## 5. Compiler Optimization

The compiler optionally runs a conservative optimization pass on the generated module (enabled by default). It folds pure constant unary/binary operations, removes unreferenced constants, deduplicates constants by exact type and value, and removes the neutral DUP/POP pair. The pass is applied independently to main and function chunks. It preserves the local-slot debug table because optimization does not renumber locals.

The optimizer compacts folded expressions and no-op pairs, remapping absolute jump targets to the new instruction indices. It refuses to fold any range entered by a jump at an interior instruction, and preserves DUP/POP pairs targeted by jumps. Operations that can fail at runtime, such as division or modulo by zero, are not folded. Expressions outside compile-time folding bounds remain in bytecode. Optimization can be disabled for debugging or benchmarking using the CLI `--no-optimize` flag.

## 6. Compatibility and Versioning

Version 1 modules remain readable and executable if they use the original main-chunk instruction set. Version 2 adds CALL, RETURN, and the function table. Version 3 adds optional embedded debug metadata without changing executable instructions. Existing v1/v2 modules remain supported; future incompatible instruction/container changes must increment the format version and define an explicit compatibility policy.


## 7. Version 4 Typed Collections

Version 4 introduces homogeneous one-dimensional arrays. ARRAY_NEW_INT, ARRAY_NEW_FLOAT, ARRAY_NEW_BOOL, and ARRAY_NEW_STRING encode the element type in the opcode and the element count in the integer operand. They consume count values in source order and push one array object.

ARRAY_GET consumes array and index, then pushes the element. ARRAY_SET consumes array, index, and value, and performs an in-place mutation. LENGTH accepts a string or array and pushes an integer length. ARRAY_PUSH consumes array and value and appends the value. ARRAY_POP consumes an array and pushes its last element.

Array values are mutable references with a fixed primitive element type. The VM validates runtime element type, zero-based index bounds, empty-pop behavior, and a configurable item-count cap. Array construction counts are verifier-bounded. Formats 1 through 3 cannot use these instructions; collection opcodes in older formats are rejected by the verifier.


### Version 6 Algebraic-Enum Instructions

Version 6 adds:

| Opcode | Operand | Stack effect | Behavior |
|---|---|---:|---|
| ENUM_NEW_PAYLOAD | Enum`|`Variant`|`type,type | 1 - payload count | Pop ordered payload values, validate each declared type, and push an immutable enum value |
| ENUM_IS | Enum`|`Variant | 0 | Replace an enum value with whether its active variant matches |
| ENUM_GET | Enum`|`Variant`|`index`|`type | 0 | Extract one payload position after validating enum type, active variant, index, and runtime payload type |

The constructor schema is bounded and names a nominal enum, a variant identifier, and an ordered payload type list. Pattern tests and payload access operands are also validated before stack analysis. Runtime extraction checks the active case again so untrusted bytecode cannot read from a different variant. These new opcodes are rejected in versions 1–5.
