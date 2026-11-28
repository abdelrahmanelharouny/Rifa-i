# Phase 14 Report — Advanced IR Optimization

## Objective

Extend the verified explicit-value IR into a useful optimization layer across basic blocks and loops, while keeping the existing stack VM, bytecode v4 container, and runtime diagnostics correct.

## Delivered

- Added IRSideEffectAnalysis and explicit operation-effect contracts for observable side effects, memory reads/writes, potential runtime traps, commonability, dead-result removability, and safe speculation.
- Added explicit DUP copy propagation.
- Added conservative dead-code elimination. Only unused total/pure operations are removed; loads, calls, array operations, division/remainder, allocations, and other potentially trapping operations remain intact.
- Added dominator-tree global common-subexpression elimination across blocks.
- Added local-load value numbering with per-slot invalidation at STORE_LOCAL and separate available-expression environments for sibling branches.
- Added natural-loop LICM using dominator back-edges, unique preheaders, and invariant-value tracking.
- LICM only speculates operations proven total and local reads whose slots are initialized before the preheader and not written in the loop. It does not hoist global reads, calls, array operations, or potentially trapping arithmetic.
- Extended IR verification to validate same-block definition order and cross-block dominance for reachable uses.
- Updated canonical value numbering to handle definitions that dominate consumers independent of block layout order.
- Added a value-materializing IR-to-bytecode path for multi-use and cross-block values. Private local slots preserve SSA value identity, and staged scratch-slot copies preserve parallel block-parameter assignments on branches and loop back-edges.
- Kept the compact stack lowering for straight-line/single-use IR.
- Added deterministic metrics to the compiler result, rifai inspect, and CLI output.
- Added Phase 14 tests and a runnable example covering global CSE, LICM, copy propagation, DCE, side-effect analysis, runtime-fault preservation, and stable deterministic output.

## Optimization Pipeline

1. Verify input IR and cross-block dominance.
2. Propagate DUP aliases.
3. Propagate/fold scalar constants and simplify constant branches.
4. Remove unreachable blocks.
5. Hoist safe loop-invariant operations to unique preheaders.
6. Eliminate common expressions available from dominating blocks.
7. Remove unused total/pure operations while preserving effects and runtime traps.
8. Repeat to a bounded fixed point.
9. Canonicalize IDs, verify output IR, analyze CFG/dominators, and collect effect metrics.

## Correctness and Compatibility

- No new bytecode opcodes and no .rbc serialization-format change; output remains bytecode v4.
- Runtime errors from division by zero, modulo by zero, uninitialized/undefined reads, invalid array access, array allocation/capacity, and function calls are not removed or speculated.
- Mutable array reads are not globally commoned. Global loads are not commoned because calls may mutate globals.
- Local loads are only commoned within a dominating memory version and are invalidated by stores to that local slot.
- LICM does not move potentially trapping arithmetic out of a loop that may execute zero times.
- Loop-carried/block-parameter edge copies use scratch slots to avoid clobbering parallel assignments.
- BytecodeToIR, the existing bytecode serializer, old .rbc formats, and the VM remain supported.
- Compiler(optimize=False) still disables IR and bytecode optimization while preserving verification and analysis; ir_optimize=True can isolate the IR optimizer.

## Validation

The Phase 14 test suite verifies:
- global CSE across dominating blocks and output parity;
- invalidation after local writes;
- loop-invariant loads and total-expression hoisting;
- copy alias replacement;
- DCE of dead total operations;
- preservation of side-effecting and potentially trapping operations;
- bytecode verification after materialized lowering;
- stable deterministic IR output and optimizer metrics.

The CI workflow also runs and inspects examples/phase14_advanced_ir_optimization.rif.
