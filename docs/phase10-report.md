# Phase 10 Report — Data-Flow and Advanced Optimization

## Objective

Build on the Phase 9 control-flow graph and extend the conservative optimizer with data-flow-driven rewrites while preserving Rifa'i program behavior, debugger usability, and bytecode compatibility.

## Delivered

- Added a CFG-aware abstract interpreter for stack values and local/global scalar constants.
- Added forward must-analysis across basic blocks. A constant fact survives a merge only when every reachable predecessor agrees on the exact type and value.
- Added constant propagation for local and global loads when a sound fact is available.
- Added constant-string LENGTH propagation and constant boolean branch simplification.
- Lowered known conditional branches to stack-correct POP/JUMP sequences.
- Rebuilt reachability after branch simplification and removed unreachable blocks/instructions.
- Preserved the required final main HALT and at least one RETURN in every function for structural verifier compatibility.
- Added block-local common-subexpression elimination for profitable, repeated, pure scalar expression ranges.
- Added local-slot write versions to CSE keys, preventing reuse after an operand variable is reassigned.
- Invalidated global constant facts after function calls and excluded mutable arrays, array accesses, and global reads from CSE.
- Added compiler-managed temporary locals only when a later expression actually reuses the cached value.
- Added deterministic debug names/types for generated temporary slots, preserving debugger inspection.
- Added optimization counters and exposed them in CLI output and structured inspection JSON.
- Kept the pass idempotent and left the bytecode v1-v4 serialization formats unchanged.

## Data-Flow Model

Each basic block receives an abstract stack plus a state containing known local and global scalar constants. The entry state starts unknown. When multiple reachable predecessor states meet, only keys present with an identical exact-type value in all inputs are preserved. This is a conservative forward must-analysis.

The analysis models stack effects for arithmetic, comparisons, branches, calls, and collection instructions. Array values and their contents remain unknown because arrays are mutable reference values. A function call invalidates all known global values because the callee may update any global; caller-local scalar values remain valid because function calls use isolated local frames.

## Dead-Code Elimination

When a conditional branch is proven, the optimizer replaces the condition-consuming jump with a POP and, for a false condition, an unconditional JUMP. It then rebuilds the CFG and removes blocks unreachable from the chunk entry. All remaining jump targets are remapped, source locations are retained, and required structural terminators are preserved.

## Common-Subexpression Elimination

CSE is limited to scalar expressions made from constants and typed local loads combined with pure unary/binary operations. It does not cross basic-block boundaries, calls, array operations, or control-flow joins. Local-slot versions are part of each expression key, so reassignment prevents stale reuse. A cache is retained only when a later identical expression actually consumes it; this avoids temporary slots and instruction overhead for one-off expressions. The pass also recognizes its own temporary-slot pattern so repeated optimizer runs remain idempotent.

## Verification and Compatibility

The existing peephole optimizer runs before data-flow analysis and again afterwards, allowing newly propagated constants to be folded and the constant pool to be compacted. Bytecode verification runs before and after transformation. Source locations, embedded source, and local debugger metadata are retained, with generated temporary locals explicitly represented. No opcode or serialized format change is required; bytecode v1-v4 remain supported.

## Statistics

OptimizationStats now includes:
- constant loads propagated;
- conditional branches folded;
- unreachable instructions removed;
- common subexpressions reused.

These metrics are included in compilation results, CLI compile output, and the bytecode optimization section in rifai inspect.

## Usage

```bash
rifai check examples/phase10_advanced_optimization.rif
rifai run examples/phase10_advanced_optimization.rif
rifai inspect examples/phase10_advanced_optimization.rif -o phase10.inspect.json
```

Expected program output:

```text
42
```

Disable the full optimization pipeline with Compiler(optimize=False) or the CLI --no-optimize option.

## Test Coverage

The Phase 10 tests cover constant propagation into expressions and branches, unreachable block removal, global invalidation across calls, conservative loop joins, repeated expression reuse, local-write invalidation, optimizer idempotence, and optimized/unoptimized output parity. CI also runs the Phase 10 example and checks all four advanced optimization counters.

## Scope Boundaries

This phase does not add new language syntax or bytecode instructions. It does not optimize mutable array expressions, CSE global reads, move expressions across basic blocks, or attempt speculative loop transformations. Those restrictions are intentional safeguards against changing observable behavior.
