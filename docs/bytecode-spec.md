# Rifa'i Bytecode Specification — Version 1

## 1. Container Format

A version 1 bytecode file uses this layout:

1. Magic header: ASCII bytes RIFAI-RBC followed by a newline.
2. UTF-8 JSON document containing the module payload.

The payload has exactly these top-level fields:

- magic: RIFAI
- format_version: integer 1
- source_name: string or null
- constants: typed constant array
- main: main code chunk

Unknown format versions are rejected. JSON constants are explicitly tagged as int, float, bool, or string. Non-finite floating-point constants are not supported.

The serializer uses deterministic key ordering and compact JSON. The reader enforces a 16 MiB maximum file size and rejects malformed fields, unknown opcodes, invalid operands, and invalid source locations.

## 2. Main Code Chunk

A code chunk contains:
- name: non-empty string
- arity: non-negative integer (zero for the version 1 main chunk)
- local_count: non-negative integer
- instructions: ordered instruction array

Version 1 modules contain one main chunk. Function chunks and call frames are reserved for Phase 4.

## 3. Instruction Encoding

Each instruction contains:
- opcode: exact opcode name
- operand: integer, string, or null according to the opcode contract
- location: optional source location (line, column, start_offset, end_offset)

Jump targets are absolute zero-based instruction indices within the main chunk.

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
| EQUAL | none | -1 | Strict same-type equality |
| NOT_EQUAL | none | -1 | Strict same-type inequality |
| LESS | none | -1 | Numeric less-than |
| LESS_EQUAL | none | -1 | Numeric less-than-or-equal |
| GREATER | none | -1 | Numeric greater-than |
| GREATER_EQUAL | none | -1 | Numeric greater-than-or-equal |
| AND | none | -1 | Eager boolean conjunction |
| OR | none | -1 | Eager boolean disjunction |
| PRINT | none | -1 | Consume and capture a printable value |
| JUMP | instruction index | 0 | Unconditional branch |
| JUMP_IF_FALSE | instruction index | -1 | Pop bool and branch when false |
| HALT | none | 0 | End the main chunk |

+1 means one value is added to the stack; -1 means one value is removed; 0 means stack height is unchanged. Binary instructions require two values before execution, and unary instructions require one.

Logical AND and OR in bytecode version 1 are eager. Phase 4 may use conditional jumps to implement source-level short-circuit evaluation if the language specification is amended accordingly.

## 4. Verification Invariants

A valid main chunk:
- Has exactly one HALT, at the final instruction.
- Uses valid opcode/operand combinations.
- References only existing constants and local slots.
- Uses in-range jump targets.
- Has no stack underflow on reachable paths.
- Has consistent stack heights at control-flow merge points.
- Cannot fall off the end of the chunk.
- Reaches HALT with an empty operand stack.

The verifier performs control-flow stack-height analysis. Runtime checks remain necessary for value types, uninitialized locals, global lookup, zero division, and resource limits.

## 5. Versioning

The serializer writes format version 1. Changes that are not backward-compatible must increment FORMAT_VERSION and define a migration or explicit rejection policy. New opcodes must be documented and implemented consistently in the verifier, disassembler, and VM before being considered supported.
