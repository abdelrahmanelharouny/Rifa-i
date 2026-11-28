"""Advanced, dominance-aware optimizations for Rifa'i IR."""

from __future__ import annotations

from dataclasses import replace

from rifai.ir.analysis import IRAnalyzer
from rifai.ir.effects import IRSideEffectAnalysis
from rifai.ir.model import (
    IRBranch,
    IRFunction,
    IRJump,
    IRModule,
    IROperation,
    IRReturn,
)


def _resolve(value_id: int, aliases: dict[int, int]) -> int:
    seen: set[int] = set()
    current = value_id
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def _rewrite_terminator(term, aliases: dict[int, int]):
    if isinstance(term, IRJump):
        return replace(term, arguments=tuple(_resolve(item, aliases) for item in term.arguments))
    if isinstance(term, IRBranch):
        return replace(
            term,
            condition=_resolve(term.condition, aliases),
            false_arguments=tuple(_resolve(item, aliases) for item in term.false_arguments),
            true_arguments=tuple(_resolve(item, aliases) for item in term.true_arguments),
        )
    if isinstance(term, IRReturn) and term.value is not None:
        return replace(term, value=_resolve(term.value, aliases))
    return term


class IRCopyPropagationPass:
    """Replace explicit DUP copies within their defining basic block."""

    name = "ir-copy-propagation"

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        changed = 0
        functions = []
        for function in (module.main, *module.functions):
            blocks = []
            for block in function.blocks:
                # A DUP result can be aliased only inside this block. Values
                # crossing a CFG edge must go through the target's block
                # parameters; carrying this map into sibling blocks could
                # violate dominance.
                aliases: dict[int, int] = {}
                operations = []
                for operation in block.operations:
                    inputs = tuple(_resolve(item, aliases) for item in operation.inputs)
                    candidate = replace(operation, inputs=inputs)
                    if (
                        candidate.opcode.value == "DUP"
                        and len(candidate.outputs) == 1
                        and len(inputs) == 1
                    ):
                        aliases[candidate.outputs[0].value_id] = inputs[0]
                        changed += 1
                        continue
                    operations.append(candidate)
                blocks.append(
                    replace(
                        block,
                        operations=tuple(operations),
                        terminator=_rewrite_terminator(block.terminator, aliases),
                    )
                )
            functions.append(replace(function, blocks=tuple(blocks)))
        return replace(module, main=functions[0], functions=tuple(functions[1:])), changed

class IRDeadCodeEliminationPass:
    """Remove unused total/pure operations while retaining every observable fault."""

    name = "ir-dead-code-elimination"

    def __init__(self) -> None:
        self.effects = IRSideEffectAnalysis()

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        removed = 0
        functions = []
        for function in (module.main, *module.functions):
            producers: dict[int, tuple[int, int]] = {}
            value_types: dict[int, str | None] = {}
            for block in function.blocks:
                for parameter in block.parameters:
                    value_types[parameter.value_id] = parameter.type_name
                for index, operation in enumerate(block.operations):
                    for output in operation.outputs:
                        producers[output.value_id] = (block.block_id, index)
                        value_types[output.value_id] = output.type_name

            live: set[tuple[int, int]] = set()
            pending: list[int] = []
            for block in function.blocks:
                if not block.reachable:
                    # Keep disconnected bytecode-lifted islands intact. They
                    # remain subject to the normal unreachable-block pass.
                    live.update(
                        (block.block_id, index)
                        for index, _ in enumerate(block.operations)
                    )
                else:
                    term = block.terminator
                    if isinstance(term, IRJump):
                        pending.extend(term.arguments)
                    elif isinstance(term, IRBranch):
                        pending.extend((
                            term.condition,
                            *term.false_arguments,
                            *term.true_arguments,
                        ))
                    elif isinstance(term, IRReturn) and term.value is not None:
                        pending.append(term.value)

                    for index, operation in enumerate(block.operations):
                        effects = self.effects.effects(operation.opcode)
                        if (
                            effects.side_effecting
                            or effects.may_trap
                            or not self.effects.is_removable_if_dead(operation, value_types)
                        ):
                            live.add((block.block_id, index))
                            pending.extend(operation.inputs)

            while pending:
                value_id = pending.pop()
                producer = producers.get(value_id)
                if producer is None or producer in live:
                    continue
                block_id, operation_index = producer
                live.add(producer)
                block = next(item for item in function.blocks if item.block_id == block_id)
                pending.extend(block.operations[operation_index].inputs)

            blocks = []
            for block in function.blocks:
                operations = tuple(
                    operation
                    for index, operation in enumerate(block.operations)
                    if (block.block_id, index) in live
                )
                removed += len(block.operations) - len(operations)
                blocks.append(replace(block, operations=operations))
            functions.append(replace(function, blocks=tuple(blocks)))
        return (
            replace(
                module,
                main=functions[0],
                functions=tuple(functions[1:]),
                requires_materialized_values=(
                    module.requires_materialized_values or removed > 0
                ),
            ),
            removed,
        )


class IRGlobalCommonSubexpressionEliminationPass:
    """Reuse deterministic SSA expressions from dominating blocks."""

    name = "ir-global-common-subexpression-elimination"

    def __init__(self) -> None:
        self.effects = IRSideEffectAnalysis()
        self.analyzer = IRAnalyzer()

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        eliminated = 0
        functions = []
        for function in (module.main, *module.functions):
            info = self.analyzer._analyze_function(function)
            reachable = set(info.reachable_blocks)
            by_id = {block.block_id: block for block in function.blocks}
            idom = dict(info.immediate_dominators)
            children: dict[int, list[int]] = {item: [] for item in reachable}
            for block_id, parent in idom.items():
                if parent is not None and block_id in children.get(parent, []):
                    continue
                if parent is not None and parent in children:
                    children[parent].append(block_id)
            for values in children.values():
                values.sort(key=lambda item: (
                    by_id[item].source_start,
                    item,
                ))

            aliases_at_exit: dict[int, dict[int, int]] = {}
            rewritten_blocks: dict[int, object] = {}

            def visit(
                block_id: int,
                inherited_aliases: dict[int, int],
                inherited_expressions: dict[tuple[object, ...], int],
            ) -> None:
                nonlocal eliminated
                aliases = dict(inherited_aliases)
                available = dict(inherited_expressions)
                block = by_id[block_id]
                operations = []
                for operation in block.operations:
                    inputs = tuple(_resolve(item, aliases) for item in operation.inputs)
                    candidate = replace(operation, inputs=inputs)
                    effects = self.effects.effects(operation.opcode)
                    if (
                        effects.commonable
                        and len(candidate.outputs) == 1
                    ):
                        output = candidate.outputs[0]
                        if candidate.opcode.value == "LOAD_LOCAL":
                            key = (
                                candidate.opcode.value,
                                candidate.operand,
                                output.type_name,
                            )
                        else:
                            key = (
                                candidate.opcode.value,
                                candidate.operand,
                                inputs,
                                output.type_name,
                            )
                        existing = available.get(key)
                        if existing is not None:
                            aliases[output.value_id] = _resolve(existing, aliases)
                            eliminated += 1
                            continue
                        available[key] = output.value_id
                    operations.append(candidate)
                    if candidate.opcode.value == "STORE_LOCAL":
                        # Local loads are commonable only within a memory
                        # version. A store kills cached reads for that slot.
                        stale = [
                            key for key in available
                            if len(key) == 3
                            and key[0] == "LOAD_LOCAL"
                            and key[1] == candidate.operand
                        ]
                        for key in stale:
                            available.pop(key, None)

                rewritten_blocks[block_id] = replace(
                    block,
                    operations=tuple(operations),
                    terminator=_rewrite_terminator(block.terminator, aliases),
                )
                aliases_at_exit[block_id] = aliases
                child_available = {
                    key: value
                    for key, value in available.items()
                    if not (key and key[0] == "LOAD_LOCAL")
                }
                for child in children.get(block_id, ()):
                    # A local may be reassigned on a sibling path that does
                    # not dominate the join. Do not carry cached memory reads
                    # into successor blocks; immutable SSA expressions remain
                    # available across the dominator tree.
                    visit(child, aliases, child_available)

            if function.blocks and function.blocks[0].block_id in reachable:
                visit(function.blocks[0].block_id, {}, {})

            blocks = []
            for block in function.blocks:
                blocks.append(
                    rewritten_blocks.get(block.block_id, block)
                )
            functions.append(replace(function, blocks=tuple(blocks)))
        return replace(module, main=functions[0], functions=tuple(functions[1:])), eliminated


class IRLoopInvariantCodeMotionPass:
    """Hoist only total operations and proven-stable local reads to loop preheaders."""

    name = "ir-loop-invariant-code-motion"

    def __init__(self) -> None:
        self.effects = IRSideEffectAnalysis()
        self.analyzer = IRAnalyzer()

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        moved_total = 0
        functions = []
        for original in (module.main, *module.functions):
            function = original
            # Recompute loop structure after each successful motion. This also
            # supports nested loops when an inner preheader belongs to an outer.
            iteration_limit = max(1, function.block_count if hasattr(function, "block_count") else len(function.blocks) * 2)
            for _ in range(iteration_limit):
                info = self.analyzer._analyze_function(function)
                reachable = set(info.reachable_blocks)
                predecessors = {key: value for key, value in info.predecessors}
                dominators = {key: set(value) for key, value in info.dominators}
                by_id = {block.block_id: block for block in function.blocks}
                loops: dict[int, set[int]] = {}
                for latch, header in info.loop_back_edges:
                    nodes = loops.setdefault(header, {header})
                    pending = [latch]
                    while pending:
                        node = pending.pop()
                        if node in nodes or node not in reachable:
                            continue
                        nodes.add(node)
                        pending.extend(
                            predecessor
                            for predecessor in predecessors.get(node, ())
                            if predecessor != header
                            and header in dominators.get(predecessor, set())
                        )

                if not loops:
                    break

                value_types: dict[int, str | None] = {}
                for value_block in function.blocks:
                    for parameter in value_block.parameters:
                        value_types[parameter.value_id] = parameter.type_name
                    for value_operation in value_block.operations:
                        for value in value_operation.outputs:
                            value_types[value.value_id] = value.type_name

                # Prefer smaller (inner) natural loops first.
                candidates = sorted(
                    loops.items(),
                    key=lambda item: (len(item[1]), item[0]),
                )
                selected = None
                for header, loop_nodes in candidates:
                    outside = sorted(
                        predecessor
                        for predecessor in predecessors.get(header, ())
                        if predecessor not in loop_nodes
                    )
                    if len(outside) != 1:
                        continue
                    preheader_id = outside[0]
                    preheader = by_id.get(preheader_id)
                    if preheader is None or not isinstance(preheader.terminator, IRJump) or preheader.terminator.target != header:
                        continue

                    local_writes = {
                        operation.operand
                        for block_id in loop_nodes
                        for operation in by_id[block_id].operations
                        if operation.opcode.value == "STORE_LOCAL"
                    }
                    initialized_slots = set(range(function.arity))
                    for block_id, block in by_id.items():
                        if block_id in loop_nodes or block_id not in dominators.get(preheader_id, set()):
                            continue
                        initialized_slots.update(
                            operation.operand
                            for operation in block.operations
                            if operation.opcode.value == "STORE_LOCAL"
                            and type(operation.operand) is int
                        )
                    initialized_slots.update(
                        operation.operand
                        for operation in preheader.operations
                        if operation.opcode.value == "STORE_LOCAL"
                        and type(operation.operand) is int
                    )
                    invariant_values: set[int] = set()
                    for block in function.blocks:
                        if block.block_id not in loop_nodes and block.block_id in dominators.get(preheader_id, set()):
                            invariant_values.update(
                                value.value_id for value in block.parameters
                            )
                            invariant_values.update(
                                output.value_id
                                for operation in block.operations
                                for output in operation.outputs
                            )

                    # Process loop blocks in dominator-tree order so an
                    # invariant defined in a loop-dominator is considered
                    # before its dependent expression.
                    depths = {item: len(dominators.get(item, ())) for item in loop_nodes}
                    ordered_nodes = sorted(
                        loop_nodes,
                        key=lambda item: (depths.get(item, 0), by_id[item].source_start, item),
                    )
                    moved_by_block: dict[int, list[IROperation]] = {}
                    invariant_ops: list[IROperation] = []
                    for block_id in ordered_nodes:
                        block = by_id[block_id]
                        keep: list[IROperation] = []
                        for operation in block.operations:
                            if len(operation.outputs) != 1:
                                keep.append(operation)
                                continue
                            is_local_read = (
                                operation.opcode.value == "LOAD_LOCAL"
                                and type(operation.operand) is int
                                and operation.operand not in local_writes
                                and operation.operand in initialized_slots
                            )
                            is_total = self.effects.is_speculatable(operation, value_types)
                            inputs_invariant = all(
                                item in invariant_values for item in operation.inputs
                            )
                            if is_local_read or (is_total and inputs_invariant):
                                invariant_ops.append(operation)
                                invariant_values.add(operation.outputs[0].value_id)
                            else:
                                keep.append(operation)
                        if len(keep) != len(block.operations):
                            moved_by_block[block_id] = keep

                    if invariant_ops:
                        selected = (preheader_id, moved_by_block, invariant_ops)
                        break

                if selected is None:
                    break

                preheader_id, moved_by_block, invariant_ops = selected
                blocks = []
                for block in function.blocks:
                    if block.block_id == preheader_id:
                        blocks.append(
                            replace(
                                block,
                                operations=(*block.operations, *invariant_ops),
                            )
                        )
                    elif block.block_id in moved_by_block:
                        blocks.append(
                            replace(block, operations=tuple(moved_by_block[block.block_id]))
                        )
                    else:
                        blocks.append(block)
                function = replace(function, blocks=tuple(blocks))
                moved_total += len(invariant_ops)
            functions.append(function)

        return replace(module, main=functions[0], functions=tuple(functions[1:])), moved_total
