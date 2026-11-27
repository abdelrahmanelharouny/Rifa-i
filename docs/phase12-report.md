# Phase 12 Report — IR-Native Optimization

## Objective

Move optimization beyond the bytecode-only pipeline by using the explicit values and control-flow edges introduced in Phase 11. Keep transformations deterministic, typed, verifiable, and conservative around runtime faults.

## Delivered

- Added scalar constant propagation over IR values and block parameters.
- Added bounded constant folding for integer/float arithmetic, string concatenation, comparisons, equality, and boolean operators.
- Added constant-boolean branch simplification while preserving the selected edge arguments and source location.
- Added reachability-based removal of blocks made dead by simplified branches.
- Added a bounded fixed-point loop so removing one edge can expose additional constant block parameters and simplifications.
- Kept division/modulo by zero, non-finite floating-point results, oversized folded integers, and oversized strings as runtime operations.
- Re-canonicalized virtual IDs and verified the complete optimized module before lowering.
- Exposed optimization counters in IR pass statistics and the compiler CLI.
- Added regression tests and a runnable Phase 12 example.

## Optimization Pipeline

1. Verify input IR.
2. Propagate known scalar constants through operations and unanimous live incoming edge values.
3. Fold supported pure scalar operations into constant definitions.
4. Replace branches whose condition is a known boolean with the selected jump.
5. Remove blocks no longer reachable from the function entry.
6. Repeat the optimization sequence to a bounded fixed point.
7. Canonicalize virtual value IDs.
8. Verify output IR and run CFG/dominator analysis.
9. Lower to bytecode and run the existing bytecode verifier.

## Safety and Compatibility

Folding uses exact runtime scalar types; booleans are not conflated with integers. The pass respects the existing conservative folding bounds (4096 integer bits and 1,000,000 string characters), rejects non-finite float results, and leaves divide/modulo-by-zero operations untouched so their diagnostics remain runtime-visible.

Only control-flow blocks proven unreachable after a constant branch is selected are removed. Unknown conditions, loop-carried values, calls, global/local memory operations, and array operations remain unchanged. The pass does not perform dead-code elimination of stack-producing operations because the current backend still lowers operations to stack bytecode; dropping such operations requires explicit value materialization in a future backend.

No opcode, VM behavior, serialized bytecode version, or .rbc container format is changed. Bytecode v1-v4 remain supported.

## Usage

Run the example:

    rifai run examples/phase12_ir_optimization.rif --no-optimize
    rifai inspect examples/phase12_ir_optimization.rif --no-optimize -o phase12.inspect.json

The inspection output includes stages.ir, stages.ir_pipeline, and stages.ir_analysis. The IR pipeline metrics now report constant_folds, branches_simplified, blocks_removed, and block_parameter_constants.

## Validation

The Phase 12 tests verify arithmetic and comparison folding, constant-branch pruning, execution parity, conservative handling of division by zero, and preservation of unknown runtime control flow and loop back-edges.
