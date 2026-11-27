"""Deterministic, verified optimization passes for Rifa'i's explicit-value IR."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import math

from rifai.bytecode.instructions import Opcode
from rifai.bytecode.module import is_constant
from rifai.ir.analysis import IRAnalysis, IRAnalyzer
from rifai.ir.model import IRBranch, IRFunction, IRJump, IRModule, IRValue, IRReturn
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
        if term.false_target == term.true_target:
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


@dataclass(frozen=True, slots=True)
class IRPassResult:
    module: IRModule
    analysis: IRAnalysis
    stats: IRPassStats


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
                            replacement = replace(operation, opcode=Opcode.CONSTANT,
                                                  inputs=(), operand=index)
                            folded += 1
                    operations.append(replacement)
                blocks.append(replace(block, operations=tuple(operations)))
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
                if isinstance(term, IRBranch) and type(known.get(term.condition)) is bool:
                    if known[term.condition]:
                        term = IRJump(term.true_target, term.true_arguments, True, term.location)
                    else:
                        term = IRJump(term.false_target, term.false_arguments, False, term.location)
                    simplified += 1
                blocks.append(replace(block, terminator=term))
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
        mapping: dict[int, int] = {}
        next_id = 0
        blocks = []
        for block in sorted(function.blocks, key=lambda item: item.source_start):
            parameters = []
            for value in block.parameters:
                mapping[value.value_id] = next_id
                parameters.append(IRValue(next_id, value.type_name))
                next_id += 1
            operations = []
            for operation in block.operations:
                inputs = tuple(mapping[value_id] for value_id in operation.inputs)
                outputs = []
                for value in operation.outputs:
                    mapping[value.value_id] = next_id
                    outputs.append(IRValue(next_id, value.type_name))
                    next_id += 1
                operations.append(replace(operation, inputs=inputs, outputs=tuple(outputs)))
            term = block.terminator
            if isinstance(term, IRJump):
                term = replace(term, arguments=tuple(mapping[value_id] for value_id in term.arguments))
            elif isinstance(term, IRBranch):
                term = replace(term, condition=mapping[term.condition],
                               false_arguments=tuple(mapping[value_id] for value_id in term.false_arguments),
                               true_arguments=tuple(mapping[value_id] for value_id in term.true_arguments))
            elif isinstance(term, IRReturn) and term.value is not None:
                term = replace(term, value=mapping[term.value])
            blocks.append(replace(block, parameters=tuple(parameters), operations=tuple(operations),
                                  terminator=term))
        return replace(function, blocks=tuple(blocks))


class IRPassManager:
    """Verify, optimize, canonicalize, and analyze IR in a deterministic order."""

    def __init__(self) -> None:
        self.verifier = IRVerifier()
        self.constants = IRConstantPropagationPass()
        self.branches = IRBranchSimplificationPass()
        self.unreachable = IRUnreachableBlockEliminationPass()
        self.numbering = IRValueNumberingPass()
        self.analyzer = IRAnalyzer()

    def run(self, module: IRModule) -> IRPassResult:
        initial = self.verifier.verify(module)
        if not initial.is_valid:
            raise ValueError("IR verification failed: " + "; ".join(initial.diagnostics[:5]))
        optimized = module
        constant_folds = branches_simplified = blocks_removed = parameter_constants = 0
        limit = module.block_count + module.operation_count + 2
        for _ in range(max(1, limit)):
            optimized, folds, propagated = self.constants.run(optimized)
            optimized, branches = self.branches.run(optimized)
            optimized, removed = self.unreachable.run(optimized)
            constant_folds += folds
            branches_simplified += branches
            blocks_removed += removed
            parameter_constants = max(parameter_constants, propagated)
            if not folds and not branches and not removed:
                break

        normalized, renumbered = self.numbering.run(optimized)
        final = self.verifier.verify(normalized)
        if not final.is_valid:
            raise RuntimeError("IR optimization pipeline produced invalid IR: "
                               + "; ".join(final.diagnostics[:5]))
        analysis = self.analyzer.analyze(normalized)
        stats = IRPassStats(
            passes=("verify-input", self.constants.name, self.branches.name,
                    self.unreachable.name, self.numbering.name, "verify-output",
                    "cfg-dominator-analysis"),
            function_count=analysis.function_count,
            block_count=analysis.block_count,
            operation_count=analysis.operation_count,
            value_count=analysis.value_count,
            edge_count=analysis.edge_count,
            loop_back_edge_count=sum(len(item.loop_back_edges) for item in analysis.functions),
            renumbered_values=renumbered,
            constant_folds=constant_folds,
            branches_simplified=branches_simplified,
            blocks_removed=blocks_removed,
            block_parameter_constants=parameter_constants,
        )
        return IRPassResult(normalized, analysis, stats)
