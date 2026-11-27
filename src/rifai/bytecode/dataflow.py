"""Conservative data-flow and local common-subexpression optimizations.

The pass operates on verified bytecode and uses the CFG as its control-flow
model. Constant facts are must-facts (retained only when every incoming edge
agrees). Global facts are invalidated by calls, and array operations remain
opaque because arrays are mutable reference values.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TypeAlias

from rifai.bytecode.cfg import ControlFlowGraph, build_control_flow_graph
from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode, stack_delta
from rifai.bytecode.module import BytecodeDebugInfo, BytecodeDebugLocal, BytecodeModule
from rifai.bytecode.verifier import MAX_LOCAL_COUNT, BytecodeVerifier

_UNKNOWN = object()
_CONSTANT_TYPES = (int, float, bool, str)
_UNARY = frozenset({Opcode.NEGATE, Opcode.NOT})
_BINARY = frozenset({
    Opcode.ADD, Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE, Opcode.MODULO,
    Opcode.EQUAL, Opcode.NOT_EQUAL, Opcode.LESS, Opcode.LESS_EQUAL,
    Opcode.GREATER, Opcode.GREATER_EQUAL, Opcode.AND, Opcode.OR,
})
_ARRAY_NEW = frozenset({
    Opcode.ARRAY_NEW_INT, Opcode.ARRAY_NEW_FLOAT,
    Opcode.ARRAY_NEW_BOOL, Opcode.ARRAY_NEW_STRING,
})
_CSE_PURE = _UNARY | _BINARY | frozenset({Opcode.CONSTANT, Opcode.LOAD_LOCAL})


@dataclass(frozen=True, slots=True)
class DataFlowStats:
    """Changes made by CFG-aware data-flow and expression-reuse passes."""

    constant_loads_propagated: int = 0
    branches_folded: int = 0
    unreachable_instructions_removed: int = 0
    common_subexpressions_eliminated: int = 0

    def __add__(self, other: DataFlowStats) -> DataFlowStats:
        return DataFlowStats(
            self.constant_loads_propagated + other.constant_loads_propagated,
            self.branches_folded + other.branches_folded,
            self.unreachable_instructions_removed + other.unreachable_instructions_removed,
            self.common_subexpressions_eliminated + other.common_subexpressions_eliminated,
        )


@dataclass(frozen=True, slots=True)
class DataFlowResult:
    """Optimized module and deterministic data-flow optimization statistics."""

    module: BytecodeModule
    stats: DataFlowStats


State: TypeAlias = tuple[dict[int, object], dict[str, object]]


@dataclass(frozen=True, slots=True)
class _ExprValue:
    key: tuple[object, ...]
    type_name: str | None
    start: int
    end: int
    pure: bool = True


def _is_constant(value: object) -> bool:
    return type(value) in _CONSTANT_TYPES


def _same_value(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _state_equal(left: State, right: State) -> bool:
    return (
        len(left[0]) == len(right[0])
        and len(left[1]) == len(right[1])
        and all(key in right[0] and _same_value(value, right[0][key]) for key, value in left[0].items())
        and all(key in right[1] and _same_value(value, right[1][key]) for key, value in left[1].items())
    )


def _join_states(states: list[State]) -> State:
    if not states:
        return {}, {}
    local_keys = set(states[0][0])
    global_keys = set(states[0][1])
    for locals_, globals_ in states[1:]:
        local_keys.intersection_update(locals_)
        global_keys.intersection_update(globals_)
    locals_out = {
        key: states[0][0][key]
        for key in local_keys
        if all(_same_value(states[0][0][key], item[0][key]) for item in states[1:])
    }
    globals_out = {
        key: states[0][1][key]
        for key in global_keys
        if all(_same_value(states[0][1][key], item[1][key]) for item in states[1:])
    }
    return locals_out, globals_out


def _pop(stack: list[object], count: int = 1) -> list[object]:
    if count <= 0:
        return []
    values = stack[-count:]
    del stack[-count:]
    return values


def _stack_heights(
    chunk: CodeChunk,
    graph: ControlFlowGraph,
    functions: dict[str, BytecodeFunction],
    return_type: str | None,
) -> dict[int, int]:
    """Compute verified block-entry stack heights; unknown values are analyzed conservatively."""
    if graph.entry_block is None:
        return {}
    by_id = {block.block_id: block for block in graph.blocks}
    heights = {graph.entry_block: 0}
    pending = deque([graph.entry_block])
    while pending:
        block_id = pending.popleft()
        height = heights[block_id]
        block = by_id[block_id]
        for instruction in chunk.instructions[block.start:block.end + 1]:
            opcode = instruction.opcode
            if opcode is Opcode.CALL:
                target = functions[instruction.operand]
                height -= target.arity
                if target.returns_value:
                    height += 1
            elif opcode in _ARRAY_NEW:
                height += 1 - instruction.operand
            elif opcode is Opcode.RETURN:
                if return_type is not None and return_type != "void":
                    height -= 1
            else:
                height += stack_delta(opcode)
        for successor in block.successors:
            existing = heights.get(successor)
            if existing is None:
                heights[successor] = height
                pending.append(successor)
            elif existing != height:
                raise ValueError(
                    f"Inconsistent stack height at block {successor} in '{chunk.name}'."
                )
    return heights


def _execute_abstract_instruction(
    instruction: Instruction,
    stack: list[object],
    locals_: dict[int, object],
    globals_: dict[str, object],
    constants: tuple[object, ...],
    functions: dict[str, BytecodeFunction],
    return_type: str | None,
) -> bool | None:
    """Transfer one instruction; return a known JUMP_IF_FALSE condition when available."""
    opcode = instruction.opcode
    if opcode is Opcode.CONSTANT:
        stack.append(constants[instruction.operand])
    elif opcode is Opcode.LOAD_LOCAL:
        stack.append(locals_.get(instruction.operand, _UNKNOWN))
    elif opcode is Opcode.STORE_LOCAL:
        value = _pop(stack)[0]
        if _is_constant(value):
            locals_[instruction.operand] = value
        else:
            locals_.pop(instruction.operand, None)
    elif opcode is Opcode.LOAD_GLOBAL:
        stack.append(globals_.get(instruction.operand, _UNKNOWN))
    elif opcode is Opcode.STORE_GLOBAL:
        value = _pop(stack)[0]
        if _is_constant(value):
            globals_[instruction.operand] = value
        else:
            globals_.pop(instruction.operand, None)
    elif opcode is Opcode.DUP:
        stack.append(stack[-1] if stack else _UNKNOWN)
    elif opcode in (Opcode.POP, Opcode.PRINT):
        _pop(stack)
    elif opcode in _UNARY:
        value = _pop(stack)[0]
        if _is_constant(value):
            from rifai.bytecode.optimizer import _UNFOLDABLE, _safe_fold
            result = _safe_fold(opcode, value)
            stack.append(result if result is not _UNFOLDABLE else _UNKNOWN)
        else:
            stack.append(_UNKNOWN)
    elif opcode in _BINARY:
        left, right = _pop(stack, 2)
        if _is_constant(left) and _is_constant(right):
            from rifai.bytecode.optimizer import _UNFOLDABLE, _safe_fold
            result = _safe_fold(opcode, left, right)
            stack.append(result if result is not _UNFOLDABLE else _UNKNOWN)
        else:
            stack.append(_UNKNOWN)
    elif opcode is Opcode.JUMP_IF_FALSE:
        condition = _pop(stack)[0]
        return condition if type(condition) is bool else None
    elif opcode is Opcode.CALL:
        target = functions[instruction.operand]
        _pop(stack, target.arity)
        globals_.clear()
        if target.returns_value:
            stack.append(_UNKNOWN)
    elif opcode in _ARRAY_NEW:
        _pop(stack, instruction.operand)
        stack.append(_UNKNOWN)
    elif opcode is Opcode.ARRAY_GET:
        _pop(stack, 2)
        stack.append(_UNKNOWN)
    elif opcode is Opcode.ARRAY_SET:
        _pop(stack, 3)
    elif opcode is Opcode.LENGTH:
        value = _pop(stack)[0]
        stack.append(len(value) if type(value) is str else _UNKNOWN)
    elif opcode is Opcode.ARRAY_PUSH:
        _pop(stack, 2)
    elif opcode is Opcode.ARRAY_POP:
        _pop(stack)
        stack.append(_UNKNOWN)
    elif opcode is Opcode.RETURN:
        if return_type is not None and return_type != "void":
            _pop(stack)
    return None


def _analyze_chunk(
    chunk: CodeChunk,
    constants: tuple[object, ...],
    functions: dict[str, BytecodeFunction],
    return_type: str | None,
) -> tuple[ControlFlowGraph, dict[int, State], dict[int, int]]:
    graph = build_control_flow_graph(chunk)
    heights = _stack_heights(chunk, graph, functions, return_type)
    if graph.entry_block is None:
        return graph, {}, heights

    reachable = set(graph.reachable_blocks)
    predecessors: dict[int, list[int]] = {block_id: [] for block_id in reachable}
    by_id = {block.block_id: block for block in graph.blocks}
    for block in graph.blocks:
        if block.block_id not in reachable:
            continue
        for successor in block.successors:
            if successor in reachable:
                predecessors[successor].append(block.block_id)

    in_states: dict[int, State] = {}
    out_states: dict[int, State] = {}
    pending = deque([graph.entry_block])
    queued = {graph.entry_block}

    while pending:
        block_id = pending.popleft()
        queued.discard(block_id)
        if block_id == graph.entry_block:
            incoming: State = ({}, {})
        else:
            preds = predecessors[block_id]
            if not preds or not all(pred in out_states for pred in preds):
                incoming = ({}, {})
            else:
                incoming = _join_states([out_states[pred] for pred in preds])
        in_states[block_id] = incoming
        locals_in, globals_in = incoming
        stack = [_UNKNOWN] * heights.get(block_id, 0)
        block = by_id[block_id]
        for instruction in chunk.instructions[block.start:block.end + 1]:
            _execute_abstract_instruction(
                instruction, stack, locals_in, globals_in,
                constants, functions, return_type,
            )
        outgoing: State = (locals_in, globals_in)
        previous = out_states.get(block_id)
        if previous is None or not _state_equal(previous, outgoing):
            out_states[block_id] = (dict(locals_in), dict(globals_in))
            for successor in block.successors:
                if successor in reachable and successor not in queued:
                    pending.append(successor)
                    queued.add(successor)

    # Blocks with no feasible predecessor in the static graph are omitted by
    # CFG reachability. Preserve an explicit empty state for safety.
    for block_id in reachable:
        in_states.setdefault(block_id, ({}, {}))
    return graph, in_states, heights


def _rewrite_and_prune_chunk(
    chunk: CodeChunk,
    constants: tuple[object, ...],
    functions: dict[str, BytecodeFunction],
    return_type: str | None,
    *,
    is_main: bool,
) -> tuple[CodeChunk, int, int, int]:
    graph, in_states, heights = _analyze_chunk(chunk, constants, functions, return_type)
    if graph.entry_block is None:
        return chunk, 0, 0, 0

    constant_indices = {
        (type(value), value): index for index, value in enumerate(constants)
    }
    by_id = {block.block_id: block for block in graph.blocks}
    transformed: list[Instruction] = []
    old_to_new: dict[int, int] = {}
    propagated = 0
    folded = 0

    for block in graph.blocks:
        entry_reachable = block.block_id in set(graph.reachable_blocks)
        start_out = len(transformed)
        if not entry_reachable:
            for old_index in range(block.start, block.end + 1):
                old_to_new[old_index] = len(transformed)
                transformed.append(chunk.instructions[old_index])
            continue

        locals_, globals_ = in_states.get(block.block_id, ({}, {}))
        locals_ = dict(locals_)
        globals_ = dict(globals_)
        stack = [_UNKNOWN] * heights.get(block.block_id, 0)
        for old_index in range(block.start, block.end + 1):
            instruction = chunk.instructions[old_index]
            emitted = instruction
            if instruction.opcode is Opcode.LOAD_LOCAL:
                value = locals_.get(instruction.operand, _UNKNOWN)
                if _is_constant(value):
                    constant_index = constant_indices.get((type(value), value))
                    if constant_index is not None:
                        emitted = Instruction(Opcode.CONSTANT, constant_index, instruction.location)
                        propagated += 1
            elif instruction.opcode is Opcode.LOAD_GLOBAL:
                value = globals_.get(instruction.operand, _UNKNOWN)
                if _is_constant(value):
                    constant_index = constant_indices.get((type(value), value))
                    if constant_index is not None:
                        emitted = Instruction(Opcode.CONSTANT, constant_index, instruction.location)
                        propagated += 1

            old_to_new[old_index] = len(transformed)
            branch = _execute_abstract_instruction(
                instruction, stack, locals_, globals_,
                constants, functions, return_type,
            )
            if instruction.opcode is Opcode.JUMP_IF_FALSE and branch is not None:
                transformed.append(Instruction(Opcode.POP, location=instruction.location))
                if branch is False:
                    transformed.append(Instruction(Opcode.JUMP, instruction.operand, instruction.location))
                folded += 1
            else:
                transformed.append(emitted)

    # Remap branches after every original instruction has a replacement offset.
    remapped: list[Instruction] = []
    for instruction in transformed:
        if instruction.opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
            target = old_to_new.get(instruction.operand)
            if target is None:
                raise ValueError(f"Optimized jump target {instruction.operand} was removed.")
            instruction = Instruction(instruction.opcode, target, instruction.location)
        remapped.append(instruction)

    rewritten = CodeChunk(chunk.name, tuple(remapped), chunk.local_count, chunk.arity)
    pruned, removed = _remove_unreachable_blocks(rewritten, is_main=is_main)
    return pruned, propagated, folded, removed


def _remove_unreachable_blocks(
    chunk: CodeChunk,
    *,
    is_main: bool,
) -> tuple[CodeChunk, int]:
    graph = build_control_flow_graph(chunk)
    if not graph.blocks:
        return chunk, 0
    by_id = {block.block_id: block for block in graph.blocks}
    keep = set(graph.reachable_blocks)

    # The verifier requires a final HALT in main and at least one RETURN in
    # every function, even when those structural sentinels are not reachable.
    required_roots: list[int] = []
    if is_main:
        required_roots.append(
            next(block.block_id for block in graph.blocks if block.end == len(chunk.instructions) - 1)
        )
    elif not any(
        any(chunk.instructions[index].opcode is Opcode.RETURN for index in range(block.start, block.end + 1))
        for block in graph.blocks if block.block_id in keep
    ):
        return_block = next(
            (
                block.block_id for block in graph.blocks
                if any(chunk.instructions[index].opcode is Opcode.RETURN for index in range(block.start, block.end + 1))
            ),
            None,
        )
        if return_block is not None:
            required_roots.append(return_block)

    pending = list(required_roots)
    while pending:
        block_id = pending.pop()
        if block_id in keep:
            continue
        keep.add(block_id)
        pending.extend(by_id[block_id].successors)

    kept_indices = [
        index
        for block in graph.blocks if block.block_id in keep
        for index in range(block.start, block.end + 1)
    ]
    if len(kept_indices) == len(chunk.instructions):
        return chunk, 0

    old_to_new = {old: new for new, old in enumerate(kept_indices)}
    output: list[Instruction] = []
    for old_index in kept_indices:
        instruction = chunk.instructions[old_index]
        if instruction.opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
            target = old_to_new.get(instruction.operand)
            if target is None:
                raise ValueError(f"Reachable jump target {instruction.operand} was removed.")
            instruction = Instruction(instruction.opcode, target, instruction.location)
        output.append(instruction)
    return (
        CodeChunk(chunk.name, tuple(output), chunk.local_count, chunk.arity),
        len(chunk.instructions) - len(output),
    )


def _expression_type(opcode: Opcode, operands: tuple[_ExprValue, ...]) -> str | None:
    types = tuple(item.type_name for item in operands)
    scalar = {"int", "float", "bool", "string"}
    if opcode is Opcode.NOT:
        return "bool" if types == ("bool",) else None
    if opcode is Opcode.NEGATE:
        return types[0] if types[0] in {"int", "float"} else None
    if opcode in (Opcode.AND, Opcode.OR):
        return "bool" if types == ("bool", "bool") else None
    if opcode in (Opcode.EQUAL, Opcode.NOT_EQUAL):
        return "bool" if types[0] == types[1] and types[0] in scalar else None
    if opcode in (Opcode.LESS, Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL):
        return "bool" if types[0] == types[1] and types[0] in {"int", "float"} else None
    if opcode is Opcode.ADD:
        return types[0] if types[0] == types[1] and types[0] in {"int", "float", "string"} else None
    if opcode in (Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.MODULO):
        allowed = {"int"} if opcode is Opcode.MODULO else {"int", "float"}
        return types[0] if types[0] == types[1] and types[0] in allowed else None
    # DIVIDE is intentionally excluded: its source-level result type is not
    # inferred here, and CSE must not invent debug metadata or assumptions.
    return None


def _token_type(value: object) -> str | None:
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "float"
    if type(value) is str:
        return "string"
    return None


def _cse_chunk(
    chunk: CodeChunk,
    constants: tuple[object, ...],
    functions: dict[str, BytecodeFunction],
    return_type: str | None,
    local_types: dict[int, str],
    preexisting_cse_slots: set[int],
) -> tuple[CodeChunk, int, tuple[tuple[int, str], ...]]:
    graph = build_control_flow_graph(chunk)
    if not graph.blocks:
        return chunk, 0, ()
    heights = _stack_heights(chunk, graph, functions, return_type)
    output: list[Instruction] = []
    old_to_new: dict[int, int] = {}
    hits = 0
    temp_types: list[tuple[int, str]] = []
    new_temp_slots: set[int] = set()
    used_temp_slots: set[int] = set()
    next_temp = chunk.local_count

    for block in graph.blocks:
        block_reachable = block.block_id in set(graph.reachable_blocks)
        cache: dict[tuple[object, ...], tuple[int, str]] = {}
        local_versions: dict[int, int] = {}
        global_epoch = 0
        stack: list[object] = [_UNKNOWN] * heights.get(block.block_id, 0)

        for index in range(block.start, block.end + 1):
            instruction = chunk.instructions[index]
            old_to_new[index] = len(output)
            opcode = instruction.opcode

            if not block_reachable:
                output.append(instruction)
                continue

            if opcode is Opcode.CONSTANT:
                value = constants[instruction.operand]
                output.append(instruction)
                stack.append(_ExprValue(("constant", type(value).__name__, value), _token_type(value), index, index))
                continue
            if opcode is Opcode.LOAD_LOCAL:
                slot = instruction.operand
                output.append(instruction)
                stack.append(_ExprValue(
                    ("local", slot, local_versions.get(slot, 0)),
                    local_types.get(slot), index, index,
                ))
                continue
            if opcode is Opcode.LOAD_GLOBAL:
                output.append(instruction)
                stack.append(_ExprValue(("global", instruction.operand, global_epoch), None, index, index))
                continue
            if opcode is Opcode.DUP:
                output.append(instruction)
                stack.append(stack[-1] if stack else _UNKNOWN)
                continue
            if opcode in _UNARY or opcode in _BINARY:
                arity = 1 if opcode in _UNARY else 2
                values = _pop(stack, arity)
                operands = tuple(values)
                typed = all(isinstance(item, _ExprValue) for item in operands)
                result_type = _expression_type(opcode, operands) if typed else None
                start = min((item.start for item in operands), default=index) if typed else index
                expression_key = (opcode.value, *(item.key for item in operands)) if typed else ()
                range_is_pure = (
                    typed
                    and all(item.pure for item in operands)
                    and index - start + 1 >= 4
                    and all(
                        chunk.instructions[position].opcode in _CSE_PURE
                        for position in range(start, index + 1)
                    )
                )
                cached = cache.get(expression_key) if range_is_pure and result_type is not None else None
                if cached is not None:
                    temp_slot, cached_type = cached
                    used_temp_slots.add(temp_slot)
                    truncate_to = old_to_new[start]
                    del output[truncate_to:]
                    replacement_index = len(output)
                    output.append(Instruction(Opcode.LOAD_LOCAL, temp_slot, instruction.location))
                    for old_index in range(start, index + 1):
                        old_to_new[old_index] = replacement_index
                    stack.append(_ExprValue(expression_key, cached_type, start, index))
                    hits += 1
                    continue

                output.append(instruction)
                value_start = start if typed else index
                expression_value = _ExprValue(
                    expression_key if typed else ("unknown-expression", index),
                    result_type,
                    value_start,
                    index,
                    pure=bool(typed and all(item.pure for item in operands)),
                )
                stack.append(expression_value)

                existing_temp = None
                if (
                    range_is_pure
                    and result_type is not None
                    and index + 2 <= block.end
                    and chunk.instructions[index + 1].opcode is Opcode.DUP
                    and chunk.instructions[index + 2].opcode is Opcode.STORE_LOCAL
                    and chunk.instructions[index + 2].operand in preexisting_cse_slots
                ):
                    existing_temp = chunk.instructions[index + 2].operand
                if existing_temp is not None:
                    cache[expression_key] = (existing_temp, result_type)
                elif range_is_pure and result_type is not None and next_temp < MAX_LOCAL_COUNT:
                    temp_slot = next_temp
                    next_temp += 1
                    temp_types.append((temp_slot, result_type))
                    new_temp_slots.add(temp_slot)
                    output.append(Instruction(Opcode.DUP, location=instruction.location))
                    output.append(Instruction(Opcode.STORE_LOCAL, temp_slot, instruction.location))
                    cache[expression_key] = (temp_slot, result_type)
                continue

            if opcode in (Opcode.STORE_LOCAL, Opcode.STORE_GLOBAL):
                values = _pop(stack)
                output.append(instruction)
                if opcode is Opcode.STORE_LOCAL:
                    local_versions[instruction.operand] = local_versions.get(instruction.operand, 0) + 1
                else:
                    global_epoch += 1
                continue
            if opcode in (Opcode.POP, Opcode.PRINT):
                _pop(stack)
                output.append(instruction)
                continue
            if opcode is Opcode.JUMP_IF_FALSE:
                _pop(stack)
                output.append(instruction)
                continue
            if opcode is Opcode.CALL:
                target = functions[instruction.operand]
                _pop(stack, target.arity)
                output.append(instruction)
                cache.clear()
                global_epoch += 1
                if target.returns_value:
                    stack.append(_UNKNOWN)
                continue
            if opcode in _ARRAY_NEW:
                cache.clear()
                _pop(stack, instruction.operand)
                stack.append(_UNKNOWN)
            elif opcode is Opcode.ARRAY_GET:
                cache.clear()
                _pop(stack, 2)
                stack.append(_UNKNOWN)
            elif opcode is Opcode.ARRAY_SET:
                cache.clear()
                _pop(stack, 3)
            elif opcode is Opcode.LENGTH:
                cache.clear()
                _pop(stack)
                stack.append(_UNKNOWN)
            elif opcode is Opcode.ARRAY_PUSH:
                cache.clear()
                _pop(stack, 2)
            elif opcode is Opcode.ARRAY_POP:
                cache.clear()
                _pop(stack)
                stack.append(_UNKNOWN)
            elif opcode is Opcode.RETURN and return_type not in (None, "void"):
                _pop(stack)
            output.append(instruction)

    # Do not keep one-off cache slots: a cache is profitable only when a
    # later expression actually reuses it. Compact surviving generated slots.
    unused_new_slots = new_temp_slots - used_temp_slots
    removed_positions: set[int] = set()
    if unused_new_slots:
        cleaned: list[Instruction] = []
        position = 0
        while position < len(output):
            if (
                output[position].opcode is Opcode.DUP
                and position + 1 < len(output)
                and output[position + 1].opcode is Opcode.STORE_LOCAL
                and output[position + 1].operand in unused_new_slots
            ):
                removed_positions.update({position, position + 1})
                position += 2
                continue
            cleaned.append(output[position])
            position += 1
        output = cleaned

    kept_new_slots = sorted(new_temp_slots & used_temp_slots)
    slot_remap = {
        old_slot: chunk.local_count + offset
        for offset, old_slot in enumerate(kept_new_slots)
    }
    if slot_remap:
        output = [
            Instruction(
                instruction.opcode,
                slot_remap.get(instruction.operand, instruction.operand)
                if instruction.opcode in (Opcode.LOAD_LOCAL, Opcode.STORE_LOCAL)
                else instruction.operand,
                instruction.location,
            )
            for instruction in output
        ]
        temp_types = [
            (slot_remap[slot], type_name)
            for slot, type_name in temp_types
            if slot in slot_remap
        ]
    else:
        temp_types = []

    if removed_positions:
        old_to_new = {
            old_index: new_position - sum(
                1 for removed_position in removed_positions if removed_position < new_position
            )
            for old_index, new_position in old_to_new.items()
        }

    # Every original branch target is a block leader, so its mapping always
    # points at the first emitted instruction for that block.
    remapped: list[Instruction] = []
    for instruction in output:
        if instruction.opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
            target = old_to_new.get(instruction.operand)
            if target is None:
                raise ValueError(f"CSE removed branch target {instruction.operand}.")
            instruction = Instruction(instruction.opcode, target, instruction.location)
        remapped.append(instruction)
    final_local_count = chunk.local_count + len(kept_new_slots)
    return CodeChunk(chunk.name, tuple(remapped), final_local_count, chunk.arity), hits, tuple(temp_types)


def optimize_module_dataflow(module: BytecodeModule) -> DataFlowResult:
    """Run fixed-point constant propagation, branch folding, DCE, and local CSE."""
    if not isinstance(module, BytecodeModule):
        raise TypeError("module must be a BytecodeModule.")
    validation = BytecodeVerifier().verify(module)
    if not validation.is_valid:
        messages = "; ".join(item.message for item in validation.diagnostics[:3])
        raise ValueError(f"Cannot analyze invalid bytecode: {messages}")

    functions = {function.name: function for function in module.functions}
    stats = DataFlowStats()
    current = module

    # Branch pruning can expose constants at subsequent joins. Rebuild the CFG
    # and repeat until no further block or instruction changes are possible.
    while True:
        before = current
        main, propagated, folded, removed = _rewrite_and_prune_chunk(
            current.main, current.constants, functions, None, is_main=True
        )
        new_functions: list[BytecodeFunction] = []
        for function in current.functions:
            chunk, p_count, b_count, r_count = _rewrite_and_prune_chunk(
                function.chunk, current.constants, functions,
                function.return_type, is_main=False,
            )
            propagated += p_count
            folded += b_count
            removed += r_count
            new_functions.append(BytecodeFunction(
                function.name, chunk, function.parameter_types, function.return_type
            ))
        current = BytecodeModule(
            constants=current.constants,
            main=main,
            source_name=current.source_name,
            format_version=current.format_version,
            functions=tuple(new_functions),
            debug_info=current.debug_info,
        )
        stats += DataFlowStats(propagated, folded, removed, 0)
        if current == before:
            break

    # CSE introduces private local slots. Only perform it when the module
    # carries embedded debug metadata so those slots can be marked and future
    # optimizer runs can recognize them without changing legacy formats.
    if current.debug_info is None:
        return DataFlowResult(current, stats)

    # CSE is block-local by design. A cache never crosses a control-flow merge,
    # loop boundary, collection operation, or function call.
    debug_maps = current.debug_info.as_mapping()
    all_temp_types: dict[str, tuple[tuple[int, str], ...]] = {}
    cse_hits = 0
    main_cse_slots = {
        slot for slot, (name, _) in debug_maps.get("<main>", {}).items()
        if name.startswith("_cse_tmp_")
    }
    main, hits, temps = _cse_chunk(
        current.main, current.constants, functions, None, {}, main_cse_slots
    )
    cse_hits += hits
    if temps:
        all_temp_types["<main>"] = temps

    new_functions = []
    for function in current.functions:
        known_types = {index: rifai_type for index, rifai_type in enumerate(function.parameter_types)}
        known_types.update({
            slot: type_name
            for slot, (_, type_name) in debug_maps.get(function.name, {}).items()
        })
        existing_cse_slots = {
            slot for slot, (name, _) in debug_maps.get(function.name, {}).items()
            if name.startswith("_cse_tmp_")
        }
        chunk, hits, temps = _cse_chunk(
            function.chunk, current.constants, functions,
            function.return_type, known_types, existing_cse_slots,
        )
        cse_hits += hits
        if temps:
            all_temp_types[function.name] = temps
        new_functions.append(BytecodeFunction(
            function.name, chunk, function.parameter_types, function.return_type
        ))

    debug_info = current.debug_info
    if debug_info is not None and all_temp_types:
        symbols_by_chunk = {
            name: list(symbols) for name, symbols in debug_info.local_symbols
        }
        for chunk_name, temps in all_temp_types.items():
            entries = symbols_by_chunk.setdefault(chunk_name, [])
            for slot, type_name in temps:
                entries.append(BytecodeDebugLocal(slot, f"_cse_tmp_{slot}", type_name))
        debug_info = BytecodeDebugInfo(
            source_text=debug_info.source_text,
            local_symbols=tuple(
                (name, tuple(symbols)) for name, symbols in symbols_by_chunk.items()
            ),
        )

    optimized = BytecodeModule(
        constants=current.constants,
        main=main,
        source_name=current.source_name,
        format_version=current.format_version,
        functions=tuple(new_functions),
        debug_info=debug_info,
    )
    stats += DataFlowStats(0, 0, 0, cse_hits)
    final_validation = BytecodeVerifier().verify(optimized)
    if not final_validation.is_valid:
        messages = "; ".join(item.message for item in final_validation.diagnostics[:3])
        raise RuntimeError(f"Data-flow optimizer produced invalid bytecode: {messages}")
    return DataFlowResult(optimized, stats)
