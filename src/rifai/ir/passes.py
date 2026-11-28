"""Deterministic, verified optimization passes for Rifa'i's explicit-value IR."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import math

from rifai.bytecode.instructions import Opcode
from rifai.bytecode.module import is_constant
from rifai.ir.analysis import IRAnalysis, IRAnalyzer
from rifai.ir.model import IRBranch, IRFunction, IRJump, IRModule, IRValue, IRReturn, IROperation
from rifai.ir.verifier import IRVerifier

_MAX_FOLDED_INT_BITS = 4096
_MAX_FOLDED_STRING_CHARS = 1_000_000
_UNFOLDABLE = object()
_UNARY_FOLDABLE = frozenset({Opcode.NEGATE, Opcode.NOT})
_BINARY_FOLDABLE = frozenset({
    Opcode.ADD, Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE,
    Opcode.MODULO, Opcode.EQUAL, Opcode.NOT_EQUAL, Opcode.LESS,
    Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL,
    Opcode.AND, Opcode.OR,
})


def _safe_fold(opcode: Opcode, left: object, right: object = None) -> object:
    """Evaluate a scalar operation only when doing so preserves VM behavior."""
    try:
        if opcode is Opcode.NEGATE:
            if type(left) not in (int, float):
                return _UNFOLDABLE
            value = -left
        elif opcode is Opcode.NOT:
            if type(left) is not bool:
                return _UNFOLDABLE
            value = not left
        elif opcode is Opcode.ADD:
            if type(left) is str and type(right) is str:
                if len(left) + len(right) > _MAX_FOLDED_STRING_CHARS:
                    return _UNFOLDABLE
                value = left + right
            elif type(left) in (int, float) and type(left) is type(right):
                if type(left) is int and max(left.bit_length(), right.bit_length()) > _MAX_FOLDED_INT_BITS:
                    return _UNFOLDABLE
                value = left + right
            else:
                return _UNFOLDABLE
        elif opcode in (Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE, Opcode.MODULO):
            if type(left) not in (int, float) or type(left) is not type(right):
                return _UNFOLDABLE
            if opcode is Opcode.MODULO and type(left) is not int:
                return _UNFOLDABLE
            if opcode in (Opcode.DIVIDE, Opcode.MODULO) and right == 0:
                return _UNFOLDABLE
            if type(left) is int:
                if opcode is Opcode.MULTIPLY and left and right:
                    if left.bit_length() + right.bit_length() > _MAX_FOLDED_INT_BITS:
                        return _UNFOLDABLE
                elif max(left.bit_length(), right.bit_length()) > _MAX_FOLDED_INT_BITS:
                    return _UNFOLDABLE
            if opcode is Opcode.SUBTRACT:
                value = left - right
            elif opcode is Opcode.MULTIPLY:
                value = left * right
            elif opcode is Opcode.DIVIDE:
                value = left / right
            else:
                value = left % right
        elif opcode in (Opcode.EQUAL, Opcode.NOT_EQUAL):
            if type(left) is not type(right) or type(left) not in (int, float, bool, str):
                return _UNFOLDABLE
            value = left == right
            if opcode is Opcode.NOT_EQUAL:
                value = not value
        elif opcode in (Opcode.LESS, Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL):
            if type(left) not in (int, float) or type(left) is not type(right):
                return _UNFOLDABLE
            if opcode is Opcode.LESS:
                value = left < right
            elif opcode is Opcode.LESS_EQUAL:
                value = left <= right
            elif opcode is Opcode.GREATER:
                value = left > right
            else:
                value = left >= right
        elif opcode in (Opcode.AND, Opcode.OR):
            if type(left) is not bool or type(right) is not bool:
                return _UNFOLDABLE
            value = left and right if opcode is Opcode.AND else left or right
        else:
            return _UNFOLDABLE
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return _UNFOLDABLE

    if not is_constant(value):
        return _UNFOLDABLE
    if type(value) is float and not math.isfinite(value):
        return _UNFOLDABLE
    if type(value) is int and value.bit_length() > _MAX_FOLDED_INT_BITS:
        return _UNFOLDABLE
    if type(value) is str and len(value) > _MAX_FOLDED_STRING_CHARS:
        return _UNFOLDABLE
    return value


def _edges(block, known: dict[int, object] | None = None):
    term = block.terminator
    if isinstance(term, IRJump):
        return ((term.target, term.arguments),)
    if isinstance(term, IRBranch):
        value = None if known is None else known.get(term.condition)
        if type(value) is bool:
            return (((term.true_target, term.true_arguments),) if value
                    else ((term.false_target, term.false_arguments),))
        if term.false_target == term.true_target and term.false_arguments == term.true_arguments:
            return ((term.false_target, term.false_arguments),)
        return ((term.false_target, term.false_arguments),
                (term.true_target, term.true_arguments))
    return ()


def _reachable_block_ids(function: IRFunction, known: dict[int, object] | None = None) -> set[int]:
    if not function.blocks:
        return set()
    by_id = {block.block_id: block for block in function.blocks}
    pending = deque([function.blocks[0].block_id])
    reachable: set[int] = set()
    while pending:
        block_id = pending.popleft()
        if block_id in reachable or block_id not in by_id:
            continue
        reachable.add(block_id)
        pending.extend(target for target, _ in _edges(by_id[block_id], known))
    return reachable


def _constant_facts(function: IRFunction, constants: tuple[object, ...]) -> tuple[dict[int, object], int]:
    """Find scalar constants, including unanimous values passed to block parameters."""
    known: dict[int, object] = {}
    parameter_constants: set[int] = set()
    limit = sum(len(block.parameters) + sum(len(op.outputs) for op in block.operations)
                for block in function.blocks) + len(function.blocks) + 2

    for _ in range(max(1, limit)):
        changed = False
        reachable = _reachable_block_ids(function, known)
        incoming: dict[int, list[tuple[int, ...]]] = {item: [] for item in reachable}
        for source in function.blocks:
            if source.block_id not in reachable:
                continue
            for target, arguments in _edges(source, known):
                if target in incoming:
                    incoming[target].append(arguments)

        for block in function.blocks:
            if block.block_id not in reachable:
                continue
            incoming_edges = incoming.get(block.block_id, [])
            for index, parameter in enumerate(block.parameters):
                candidates = [known[args[index]] for args in incoming_edges
                              if index < len(args) and args[index] in known]
                if (incoming_edges and len(candidates) == len(incoming_edges) and candidates
                    and all(type(item) is type(candidates[0]) and item == candidates[0]
                            for item in candidates[1:])
                    and parameter.value_id not in known):
                    known[parameter.value_id] = candidates[0]
                    parameter_constants.add(parameter.value_id)
                    changed = True

            for operation in block.operations:
                if not operation.outputs:
                    continue
                output_id = operation.outputs[0].value_id
                value = _UNFOLDABLE
                if operation.opcode is Opcode.CONSTANT:
                    index = operation.operand
                    if type(index) is int and 0 <= index < len(constants):
                        value = constants[index]
                elif operation.opcode is Opcode.DUP and operation.inputs:
                    value = known.get(operation.inputs[0], _UNFOLDABLE)
                elif operation.opcode in _UNARY_FOLDABLE and len(operation.inputs) == 1:
                    source = known.get(operation.inputs[0], _UNFOLDABLE)
                    if source is not _UNFOLDABLE:
                        value = _safe_fold(operation.opcode, source)
                elif operation.opcode in _BINARY_FOLDABLE and len(operation.inputs) == 2:
                    left = known.get(operation.inputs[0], _UNFOLDABLE)
                    right = known.get(operation.inputs[1], _UNFOLDABLE)
                    if left is not _UNFOLDABLE and right is not _UNFOLDABLE:
                        value = _safe_fold(operation.opcode, left, right)
                if value is not _UNFOLDABLE and output_id not in known:
                    known[output_id] = value
                    changed = True
        if not changed:
            break
    return known, len(parameter_constants)


def _requires_materialized_values(function: IRFunction) -> bool:
    definitions: dict[int, int] = {}
    uses: dict[int, list[int]] = {}
    for block in function.blocks:
        for parameter in block.parameters:
            definitions[parameter.value_id] = block.block_id
        for operation in block.operations:
            for output in operation.outputs:
                definitions[output.value_id] = block.block_id
            for value_id in operation.inputs:
                uses.setdefault(value_id, []).append(block.block_id)
        term = block.terminator
        if isinstance(term, IRJump):
            values = term.arguments
        elif isinstance(term, IRBranch):
            values = (
                term.condition,
                *term.false_arguments,
                *term.true_arguments,
            )
        elif isinstance(term, IRReturn) and term.value is not None:
            values = (term.value,)
        else:
            values = ()
        for value_id in values:
            uses.setdefault(value_id, []).append(block.block_id)

    return any(
        len(uses.get(value_id, ())) != 1
        or uses[value_id][0] != definition_block
        for value_id, definition_block in definitions.items()
    )


@dataclass(frozen=True, slots=True)
class IRPassStats:
    passes: tuple[str, ...]
    function_count: int
    block_count: int
    operation_count: int
    value_count: int
    edge_count: int
    loop_back_edge_count: int
    renumbered_values: int
    constant_folds: int = 0
    branches_simplified: int = 0
    blocks_removed: int = 0
    block_parameter_constants: int = 0
    dead_operations_removed: int = 0
    copy_propagations: int = 0
    global_cse_eliminated: int = 0
    loop_invariants_hoisted: int = 0
    side_effecting_operations: int = 0


@dataclass(frozen=True, slots=True)
class IRPassResult:
    module: IRModule
    analysis: IRAnalysis
    stats: IRPassStats


def _prune_folded_constant_materializations(function: IRFunction, blocks: list) -> list:
    """Remove same-block constants whose only remaining use is a fold POP.

    The IR-to-stack-bytecode lowerer emits operations in order. A folded
    operation therefore consumes its original stack operands with explicit
    POP operations before materializing the folded constant. When an operand
    is a same-block CONSTANT used nowhere else, both its push and matching POP
    are redundant. Repeating this rule also collapses nested folded trees.
    Block parameters and values used across CFG edges are deliberately kept.
    """
    current = blocks
    while True:
        uses: dict[int, int] = {}
        definitions: dict[tuple[int, int], int] = {}

        for block_index, block in enumerate(current):
            for operation_index, operation in enumerate(block.operations):
                for value_id in operation.inputs:
                    uses[value_id] = uses.get(value_id, 0) + 1
                for output in operation.outputs:
                    definitions[(block.block_id, output.value_id)] = operation_index

            term = block.terminator
            if isinstance(term, IRJump):
                values = term.arguments
            elif isinstance(term, IRBranch):
                values = (
                    term.condition,
                    *term.false_arguments,
                    *term.true_arguments,
                )
            elif isinstance(term, IRReturn) and term.value is not None:
                values = (term.value,)
            else:
                values = ()
            for value_id in values:
                uses[value_id] = uses.get(value_id, 0) + 1

        rewritten = []
        removed_any = False
        for block in current:
            operations = block.operations
            remove_positions: set[int] = set()
            for pop_index, operation in enumerate(operations):
                if operation.opcode is not Opcode.POP or len(operation.inputs) != 1:
                    continue
                value_id = operation.inputs[0]
                definition_index = definitions.get((block.block_id, value_id))
                if definition_index is None or uses.get(value_id) != 1:
                    continue
                definition = operations[definition_index]
                if (
                    definition.opcode is Opcode.CONSTANT
                    and len(definition.outputs) == 1
                    and definition.outputs[0].value_id == value_id
                ):
                    remove_positions.update((definition_index, pop_index))
            if remove_positions:
                removed_any = True
                rewritten.append(
                    replace(
                        block,
                        operations=tuple(
                            operation
                            for index, operation in enumerate(operations)
                            if index not in remove_positions
                        ),
                    )
                )
            else:
                rewritten.append(block)
        if not removed_any:
            return current
        current = rewritten


class IRConstantPropagationPass:
    """Fold scalar operations from constants, including constants at CFG joins."""
    name = "ir-constant-propagation"

    def run(self, module: IRModule) -> tuple[IRModule, int, int]:
        constants = list(module.constants)
        indices = {(type(value), value): index for index, value in enumerate(constants)}
        folded = propagated = 0
        functions = []
        for function in (module.main, *module.functions):
            known, count = _constant_facts(function, tuple(constants))
            propagated += count
            blocks = []
            for block in function.blocks:
                operations = []
                for operation in block.operations:
                    replacement = operation
                    if (operation.opcode in (_UNARY_FOLDABLE | _BINARY_FOLDABLE)
                        and len(operation.outputs) == 1
                        and all(value_id in known for value_id in operation.inputs)):
                        operands = [known[value_id] for value_id in operation.inputs]
                        value = _safe_fold(operation.opcode, operands[0],
                                           operands[1] if len(operands) == 2 else None)
                        if value is not _UNFOLDABLE:
                            key = (type(value), value)
                            index = indices.get(key)
                            if index is None:
                                index = len(constants)
                                constants.append(value)
                                indices[key] = index
                            # Preserve stack semantics: the bytecode lowerer emits
                            # operations in order, so consume the original operands
                            # before pushing the folded result.
                            for value_id in reversed(operation.inputs):
                                operations.append(
                                    IROperation(
                                        opcode=Opcode.POP,
                                        outputs=(),
                                        inputs=(value_id,),
                                        location=operation.location,
                                    )
                                )
                            replacement = replace(
                                operation, opcode=Opcode.CONSTANT,
                                inputs=(), operand=index
                            )
                            folded += 1
                    operations.append(replacement)
                blocks.append(replace(block, operations=tuple(operations)))
            blocks = _prune_folded_constant_materializations(function, blocks)
            functions.append(replace(function, blocks=tuple(blocks)))
        return (replace(module, constants=tuple(constants), main=functions[0],
                        functions=tuple(functions[1:])), folded, propagated)


class IRBranchSimplificationPass:
    """Replace branches with constant boolean conditions by their selected edge."""
    name = "ir-branch-simplification"

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        simplified = 0
        functions = []
        for function in (module.main, *module.functions):
            known, _ = _constant_facts(function, module.constants)
            blocks = []
            for block in function.blocks:
                term = block.terminator
                operations = block.operations
                if isinstance(term, IRBranch) and type(known.get(term.condition)) is bool:
                    # JUMP_IF_FALSE consumes its condition in the stack VM.
                    # Once the branch becomes an unconditional jump, preserve
                    # that stack effect explicitly in the lowered bytecode.
                    operations = (*operations, IROperation(
                        opcode=Opcode.POP,
                        outputs=(),
                        inputs=(term.condition,),
                        location=term.location,
                    ))
                    if known[term.condition]:
                        term = IRJump(term.true_target, term.true_arguments, True, term.location)
                    else:
                        term = IRJump(term.false_target, term.false_arguments, False, term.location)
                    simplified += 1
                blocks.append(replace(block, operations=operations, terminator=term))
            functions.append(replace(function, blocks=tuple(blocks)))
        return replace(module, main=functions[0], functions=tuple(functions[1:])), simplified


class IRUnreachableBlockEliminationPass:
    """Remove blocks no longer reachable after constant branch simplification."""
    name = "ir-unreachable-block-elimination"

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        removed = 0
        functions = []
        for function in (module.main, *module.functions):
            reachable = _reachable_block_ids(function)
            blocks = tuple(replace(block, reachable=True) for block in function.blocks
                           if block.block_id in reachable)
            removed += len(function.blocks) - len(blocks)
            functions.append(replace(function, blocks=blocks))
        return replace(module, main=functions[0], functions=tuple(functions[1:])), removed


class IRValueNumberingPass:
    """Canonicalize virtual value IDs in deterministic block/instruction order."""
    name = "canonical-value-numbering"

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        functions = tuple(self._run_function(function) for function in (module.main, *module.functions))
        return replace(module, main=functions[0], functions=functions[1:]), module.value_count

    @staticmethod
    def _run_function(function: IRFunction) -> IRFunction:
        # Assign every definition before rewriting any use. Cross-block
        # dominating definitions are legal after Phase 14, so a one-pass
        # use-as-you-go renumbering would fail when a consumer is laid out
        # before its dominating producer.
        ordered = tuple(sorted(
            function.blocks,
            key=lambda item: (item.source_start, item.block_id),
        ))
        mapping: dict[int, int] = {}
        next_id = 0
        for block in ordered:
            for value in block.parameters:
                mapping[value.value_id] = next_id
                next_id += 1
            for operation in block.operations:
                for value in operation.outputs:
                    mapping[value.value_id] = next_id
                    next_id += 1

        def mapped(value_id: int) -> int:
            try:
                return mapping[value_id]
            except KeyError as exc:
                raise ValueError(
                    f"Cannot canonicalize undefined IR value %{value_id}."
                ) from exc

        blocks = []
        for block in function.blocks:
            parameters = tuple(
                IRValue(mapped(value.value_id), value.type_name)
                for value in block.parameters
            )
            operations = tuple(
                replace(
                    operation,
                    inputs=tuple(mapped(value_id) for value_id in operation.inputs),
                    outputs=tuple(
                        IRValue(mapped(value.value_id), value.type_name)
                        for value in operation.outputs
                    ),
                )
                for operation in block.operations
            )
            term = block.terminator
            if isinstance(term, IRJump):
                term = replace(
                    term,
                    arguments=tuple(mapped(value_id) for value_id in term.arguments),
                )
            elif isinstance(term, IRBranch):
                term = replace(
                    term,
                    condition=mapped(term.condition),
                    false_arguments=tuple(mapped(value_id) for value_id in term.false_arguments),
                    true_arguments=tuple(mapped(value_id) for value_id in term.true_arguments),
                )
            elif isinstance(term, IRReturn) and term.value is not None:
                term = replace(term, value=mapped(term.value))
            blocks.append(replace(
                block,
                parameters=parameters,
                operations=operations,
                terminator=term,
            ))
        return replace(function, blocks=tuple(blocks))


class IRPassManager:
    """Verify, optimize, canonicalize, and analyze IR to a bounded fixed point."""

    def __init__(self) -> None:
        from rifai.ir.advanced_passes import (
            IRCopyPropagationPass,
            IRDeadCodeEliminationPass,
            IRGlobalCommonSubexpressionEliminationPass,
            IRLoopInvariantCodeMotionPass,
        )
        from rifai.ir.effects import IRSideEffectAnalysis

        self.verifier = IRVerifier()
        self.constants = IRConstantPropagationPass()
        self.branches = IRBranchSimplificationPass()
        self.unreachable = IRUnreachableBlockEliminationPass()
        self.copy = IRCopyPropagationPass()
        self.dce = IRDeadCodeEliminationPass()
        self.global_cse = IRGlobalCommonSubexpressionEliminationPass()
        self.licm = IRLoopInvariantCodeMotionPass()
        self.effects = IRSideEffectAnalysis()
        self.numbering = IRValueNumberingPass()
        self.analyzer = IRAnalyzer()

    def run(self, module: IRModule, *, optimize: bool = True) -> IRPassResult:
        initial = self.verifier.verify(module)
        if not initial.is_valid:
            raise ValueError("IR verification failed: " + "; ".join(initial.diagnostics[:5]))
        optimized = module
        constant_folds = branches_simplified = blocks_removed = parameter_constants = 0
        dead_removed = copies = cse_removed = hoisted = 0
        if optimize:
            limit = module.block_count + module.operation_count + 4
            for _ in range(max(1, limit)):
                before = optimized
                optimized, copy_count = self.copy.run(optimized)
                optimized, folds, propagated = self.constants.run(optimized)
                optimized, branches = self.branches.run(optimized)
                optimized, unreachable = self.unreachable.run(optimized)
                optimized, moved = self.licm.run(optimized)
                optimized, common = self.global_cse.run(optimized)
                optimized, dead = self.dce.run(optimized)

                copies += copy_count
                constant_folds += folds
                branches_simplified += branches
                blocks_removed += unreachable
                hoisted += moved
                cse_removed += common
                dead_removed += dead
                parameter_constants = max(parameter_constants, propagated)
                if optimized == before:
                    break

        normalized, renumbered = self.numbering.run(optimized)
        requires_materialized = module.requires_materialized_values or (
            optimize
            and any(
                _requires_materialized_values(function)
                for function in (normalized.main, *normalized.functions)
            )
        )
        normalized = replace(
            normalized,
            requires_materialized_values=requires_materialized,
        )
        final = self.verifier.verify(normalized)
        if not final.is_valid:
            raise RuntimeError(
                "IR optimization pipeline produced invalid IR: "
                + "; ".join(final.diagnostics[:5])
            )
        analysis = self.analyzer.analyze(normalized)
        effects = self.effects.analyze(normalized)
        active_passes = (
            "verify-input",
            self.copy.name,
            self.constants.name,
            self.branches.name,
            self.unreachable.name,
            self.licm.name,
            self.global_cse.name,
            self.dce.name,
            self.numbering.name,
            "verify-output",
            "cfg-dominator-analysis",
            "side-effect-analysis",
        )
        stats = IRPassStats(
            passes=active_passes if optimize else (
                "verify-input",
                self.numbering.name,
                "verify-output",
                "cfg-dominator-analysis",
                "side-effect-analysis",
            ),
            function_count=analysis.function_count,
            block_count=analysis.block_count,
            operation_count=analysis.operation_count,
            value_count=analysis.value_count,
            edge_count=analysis.edge_count,
            loop_back_edge_count=sum(
                len(item.loop_back_edges) for item in analysis.functions
            ),
            renumbered_values=renumbered,
            constant_folds=constant_folds,
            branches_simplified=branches_simplified,
            blocks_removed=blocks_removed,
            block_parameter_constants=parameter_constants,
            dead_operations_removed=dead_removed,
            copy_propagations=copies,
            global_cse_eliminated=cse_removed,
            loop_invariants_hoisted=hoisted,
            side_effecting_operations=effects.side_effecting_operations,
        )
        return IRPassResult(normalized, analysis, stats)
