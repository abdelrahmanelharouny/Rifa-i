# Rifa'i Bytecode Specification

## 1. Container Format

The bytecode file begins with the ASCII magic header RIFAI-RBC followed by a newline, then a UTF-8 JSON payload.

### Version 1

Version 1 contains exactly:
- magic: RIFAI
- format_version: integer 1
- source_name: string or null
- constants: typed constant array
- main: main code chunk

### Version 2

Version 2 contains all version 1 fields plus:
- functions: array of function records.

A function record contains:
- name: unique non-empty function name
- parameter_types: ordered array of int, float, bool, or string
- return_type: one of int, float, bool, string, or void
- chunk: executable code chunk

The serializer writes version 2 by default and retains a version 1 writer for compatibility tooling. The reader accepts versions 1 and 2 and rejects unsupported versions. Constants are tagged as int, float, bool, or string; non-finite floats are forbidden. JSON keys must be unique. The maximum file size is 16 MiB.

## 2. Code Chunks and Frames

A code chunk contains:
- name: non-empty name (<main> for the main program)
- arity: non-negative integer
- local_count: number of local slots
- instructions: ordered instruction array

For a function chunk, arity must equal the length of its parameter signature and local_count must be at least arity. The first arity slots hold parameters in declaration order. Other locals use the remaining zero-based slots.

Version 1 modules contain only the main chunk. Version 2 modules contain one main chunk and zero or more function chunks.

## 3. Instruction Encoding

Each instruction contains:
- opcode: exact opcode name
- operand: integer, string, or null according to the opcode contract
- location: optional source location (line, column, start_offset, end_offset)

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
| AND / OR | none | -1 | Eager boolean conjunction/disjunction |
| PRINT | none | -1 | Consume and capture a printable value |
| JUMP | instruction index | 0 | Unconditional branch |
| JUMP_IF_FALSE | instruction index | -1 | Pop bool and branch when false |
| CALL | function name | -arity + returns-value | Invoke a function with arguments already on the stack |
| RETURN | none | function terminal | Return the top value from value functions; void functions return no value |
| HALT | none | 0 | End the main chunk |

+1 means a value is added to the stack; -1 means a value is removed; 0 means stack height is unchanged. CALL consumes exactly the callee's arity. It pushes one result for non-void functions and no result for void functions. RETURN is valid only in function chunks; HALT is valid only in the main chunk.

## 4. Verification Invariants

The verifier validates the main chunk and every function chunk:
- Supported bytecode version and typed constants.
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
- Structural caps on constant count, function count, instruction count, local slots, and constant-string size.

Runtime checks remain necessary for dynamic value types, uninitialized locals, undefined globals, zero division, finite floating-point results, and execution/stack/call-depth, integer-size, string-size, and captured-output limits.

## 5. Compiler Optimization

The compiler optionally runs a conservative optimization pass on the generated module (enabled by default). It folds pure constant unary/binary operations, removes unreferenced constants, deduplicates constants by exact type and value, and removes the neutral DUP/POP pair. The pass is applied independently to main and function chunks.

The optimizer compacts folded expressions and no-op pairs, remapping absolute jump targets to the new instruction indices. It refuses to fold any range entered by a jump at an interior instruction, and preserves DUP/POP pairs targeted by jumps. Operations that can fail at runtime, such as division or modulo by zero, are not folded. Expressions outside compile-time folding bounds remain in bytecode. Optimization can be disabled for debugging or benchmarking using the CLI --no-optimize flag.

## 6. Compatibility and Versioning

Version 1 modules remain readable and executable if they use the original main-chunk instruction set. Version 2 adds CALL, RETURN, and the function table. The serializer writes version 2 by default. Phase 5 does not change the bytecode wire format; any future incompatible change must increment the format version and define an explicit compatibility policy.
