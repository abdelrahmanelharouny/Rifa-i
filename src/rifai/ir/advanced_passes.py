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
                            is_total = self.effects.effects(operation.opcode).speculatable
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
