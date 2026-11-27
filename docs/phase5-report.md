# Phase 5 Delivery Report — Optimization and Final Hardening

## Delivered

### Compiler optimization
- Added a conservative bytecode optimizer for unary and binary constant expressions.
- Added type-aware constant deduplication and unused constant-pool removal.
- Added removal of the stack-neutral DUP/POP pair.
- Applied the same pass to the main chunk and all function chunks.
- Remapped absolute jump targets after instruction compaction and preserved source locations.
- Refused unsafe folds when control flow enters an expression internally; retained targeted DUP/POP pairs.
- Kept potentially failing work, including division/modulo by zero and out-of-bound folds, at runtime.
- Added an enabled-by-default compiler option and the CLI --no-optimize switch.

### Runtime hardening
- Enforced positive integer limits for instruction count, operand stack, call depth, integer bit length, string length, and total captured output.
- Bounded local frame sizes, constant-string sizes, function metadata, and code-chunk instruction counts.
- Rejected invalid initial-global containers and over-limit initial strings.
- Checked string concatenation size before allocating the concatenated result.

### Bytecode hardening
- Added source-map coordinate validation and structural complexity limits to the verifier.
- Bounded file reads to the 16 MiB format limit plus one byte.
- Made writes atomic with a same-directory temporary file and replacement.
- Preserved deterministic JSON serialization and v1/v2 compatibility.

### Validation and developer experience
- Added optimizer, parity, idempotence, control-flow, source-location, serializer, VM-limit, and CLI tests.
- Added a Phase 5 end-to-end example.
- Added a reproducible standard-library benchmark comparing optimized and unoptimized compilation/execution.
- Updated compiler architecture, bytecode specification, README, and package version.

## Compatibility

Phase 5 does not change the bytecode wire format. Existing version 1 and version 2 modules remain supported. Optimization can be disabled without changing source-language semantics.

## Benchmark methodology

Run `python benchmarks/benchmark_pipeline.py` from the repository root. The script validates equal output before reporting local median/best execution times, instruction counts, and runtime ratio. Timing depends on the host environment and is not a CI threshold.
