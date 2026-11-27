# Phase 11 Report — Intermediate Representation and Multi-Pass Compiler

## Objective

Introduce a typed, target-independent compiler IR with explicit data-flow values, verified control-flow edges, deterministic analysis passes, and a bytecode lowering backend. Preserve the existing language semantics, VM, debugger, and portable bytecode format.

## Delivered

- Added the independent `rifai.ir` package and immutable IR models:
  - `IRModule`, `IRFunction`, and `IRBlock`;
  - typed `IRValue` definitions and explicit `IROperation` inputs/outputs;
  - block parameters for operand-stack values entering a block;
  - explicit jump, branch, return, and halt terminators;
  - source locations, local-slot metadata, function signatures, and constants.
- Added `BytecodeToIR` to lift only verified bytecode into explicit-value IR.
- Added an IR verifier for unique value definitions, local use-before-definition, operation arity, function calls, local slots, terminators, branch targets, and live block-parameter/edge compatibility.
- Added deterministic virtual-value numbering as a real IR canonicalization pass.
- Added CFG analysis for each function and main: predecessors, reachability, dominators, immediate dominators, and loop back-edges.
- Added `IRPassManager` with input verification, canonical numbering, output verification, and analysis/statistics.
- Added `IRToBytecode` to reconstruct blocks, stack-machine operations, jumps, and terminators; the result is verified by the existing bytecode verifier.
- Integrated the IR pipeline into `Compiler.compile`; successful `CompilationResult` now exposes `ir_module`, `ir_stats`, and `ir_analysis`.
- Added structured IR, pass, and dominator output to `rifai inspect`.
- Exported the IR models and pipeline through the public `rifai` and `rifai.ir` APIs.
- Added a Phase 11 example, round-trip tests, malformed-IR tests, deterministic-pass tests, and CI smoke validation.
- Bumped the Python package version to 0.12.0.

## IR Model

The current IR is an explicit-value, stack-to-SSA representation. Each bytecode stack value is assigned a virtual value ID. A block's input stack is represented by block parameters, and outgoing edges pass explicit argument IDs to the target block parameters. This makes stack merges and control-flow relationships inspectable without embedding bytecode offsets in each data-flow reference.

Local and global variables remain explicit load/store operations. This is intentional: it provides a safe migration path from the working source frontend and VM while allowing later IR-native lowering and optimization work to move into this representation.

## Pass Pipeline

The deterministic pass sequence is:

1. Verify input IR.
2. Canonicalize virtual value IDs in function/block/instruction order.
3. Verify canonicalized IR again.
4. Analyze reachability, predecessor relationships, dominators, immediate dominators, and loop back-edges.

The analysis reports function, block, operation, value, and edge counts, plus per-function flow details. Unreachable blocks are represented and reported; live-edge compatibility is checked separately from structurally valid dead regions.

## Lowering and Compatibility

The lowerer lays out blocks in original source order, converts terminators back to jump/branch/return/halt bytecode, remaps target offsets, and preserves constants, local frames, function signatures, source maps, and embedded debugger metadata. The lowered result passes the existing BytecodeVerifier before being returned by the compiler.

No new bytecode instructions or serialized format versions were added. Bytecode v1-v4 remain supported, and .rbc serialization is unchanged.

## Usage

```python
from rifai import Compiler, IRVerifier

result = Compiler().compile("print(20 + 22);")
assert result.is_success
assert IRVerifier().verify(result.ir_module).is_valid
print(result.ir_module.as_dict())
print(result.ir_analysis.as_dict())
```

Inspect the same data from a source file:

```bash
rifai inspect examples/phase11_ir_pipeline.rif -o phase11.inspect.json
```

The report exposes `stages.ir`, `stages.ir_pipeline`, and `stages.ir_analysis`.

## Tests and Example

The Phase 11 tests cover compiler integration, bytecode-to-IR-to-bytecode round trips across functions/branches/loops/arrays, block parameters, loop back-edges and dominators, undefined values, deterministic value numbering, and the no-optimization compiler mode.

The integration example `examples/phase11_ir_pipeline.rif` uses an array, function call, and loop; its expected output is `10`. CI checks the output and verifies the structured IR report includes blocks and dominator analysis.

## Architecture Boundary

This is a transitional IR integration: the proven AST-to-bytecode generator remains in place, then its verified output is lifted into IR, passed through the IR manager, and lowered back to bytecode. This avoids a risky rewrite of frontend semantics and debugger mappings while creating a clear migration boundary for future direct AST-to-IR lowering and IR-native optimization passes.
