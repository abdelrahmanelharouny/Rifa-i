"""Conservative, semantics-preserving bytecode optimizations."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode
from rifai.bytecode.module import BytecodeModule, is_constant
from rifai.bytecode.verifier import BytecodeVerifier

_MAX_FOLDED_INT_BITS = 4096
_MAX_FOLDED_STRING_CHARS = 1_000_000
_UNFOLDABLE = object()

_UNARY_OPS = frozenset({Opcode.NEGATE, Opcode.NOT})
_BINARY_OPS = frozenset(
    {
        Opcode.ADD,
        Opcode.SUBTRACT,
        Opcode.MULTIPLY,
        Opcode.DIVIDE,
        Opcode.MODULO,
        Opcode.EQUAL,
        Opcode.NOT_EQUAL,
        Opcode.LESS,
        Opcode.LESS_EQUAL,
        Opcode.GREATER,
        Opcode.GREATER_EQUAL,
        Opcode.AND,
        Opcode.OR,
    }
)


@dataclass(slots=True)
class _Node:
    """One emitted instruction or a removed, stack-neutral instruction range."""

    instruction: Instruction | None
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class OptimizationStats:
    """Instruction and constant-pool changes from one optimization pass."""

    original_instruction_count: int
    optimized_instruction_count: int
    folded_expressions: int
    removed_noops: int
    constants_before: int
    constants_after: int
    constant_loads_propagated: int = 0
    branches_folded: int = 0
    unreachable_instructions_removed: int = 0
    common_subexpressions_eliminated: int = 0

    @property
    def instructions_removed(self) -> int:
        return self.original_instruction_count - self.optimized_instruction_count

    @property
    def reduction_percent(self) -> float:
        if self.original_instruction_count == 0:
            return 0.0
        return 100.0 * self.instructions_removed / self.original_instruction_count


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Optimized bytecode module together with deterministic pass statistics."""

    module: BytecodeModule
    stats: OptimizationStats


def _safe_fold(opcode: Opcode, left: object, right: object = None) -> object:
    """Evaluate one pure operation, or return the sentinel when it must stay at runtime."""
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
        elif opcode in (
            Opcode.LESS,
            Opcode.LESS_EQUAL,
            Opcode.GREATER,
            Opcode.GREATER_EQUAL,
        ):
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
    except (ArithmeticError, TypeError, ValueError):
        return _UNFOLDABLE

    if not is_constant(value):
        return _UNFOLDABLE
    if type(value) is int and value.bit_length() > _MAX_FOLDED_INT_BITS:
        return _UNFOLDABLE
    if type(value) is str and len(value) > _MAX_FOLDED_STRING_CHARS:
        return _UNFOLDABLE
    return value


class BytecodeOptimizer:
    """Apply constant folding, jump remapping and stack-neutral peephole cleanup.

    Collapsed instruction ranges are tracked back to their original indices.
    Jump targets are remapped after each chunk is compacted. A fold is refused
    whenever a jump enters the middle of the expression being replaced.
    """

    def optimize(self, module: BytecodeModule, *, _advanced: bool = True) -> OptimizationResult:
        if not isinstance(module, BytecodeModule):
            raise TypeError("module must be a BytecodeModule.")
        if _advanced:
            # Keep the original peephole pass as a verified baseline, then run
            # CFG-aware data-flow/DCE/CSE and one final peephole pass so newly
            # propagated constants are folded and the constant pool is compacted.
            baseline = self.optimize(module, _advanced=False)
            from rifai.bytecode.dataflow import optimize_module_dataflow

            dataflow = optimize_module_dataflow(baseline.module)
            final = (
                self.optimize(dataflow.module, _advanced=False)
                if dataflow.module != baseline.module
                else baseline
            )
            extra = dataflow.stats
            return OptimizationResult(
                final.module,
                OptimizationStats(
                    original_instruction_count=baseline.stats.original_instruction_count,
                    optimized_instruction_count=final.stats.optimized_instruction_count,
                    folded_expressions=baseline.stats.folded_expressions
                    + (final.stats.folded_expressions if final is not baseline else 0),
                    removed_noops=baseline.stats.removed_noops
                    + (final.stats.removed_noops if final is not baseline else 0),
                    constants_before=len(module.constants),
                    constants_after=len(final.module.constants),
                    constant_loads_propagated=extra.constant_loads_propagated,
                    branches_folded=extra.branches_folded,
                    unreachable_instructions_removed=extra.unreachable_instructions_removed,
                    common_subexpressions_eliminated=extra.common_subexpressions_eliminated,
                ),
            )

        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            messages = "; ".join(item.message for item in validation.diagnostics[:3])
            raise ValueError(f"Cannot optimize invalid bytecode: {messages}")

        constants = list(module.constants)
        constant_indices = {
            (type(value), value): index for index, value in enumerate(constants)
        }
        folded = 0
        removed = 0

        def intern(value: object) -> int:
            key = (type(value), value)
            existing = constant_indices.get(key)
            if existing is not None:
                return existing
            index = len(constants)
            constants.append(value)  # type: ignore[arg-type]
            constant_indices[key] = index
            return index

        def optimize_chunk(chunk: CodeChunk) -> CodeChunk:
            nonlocal folded, removed
            jump_targets = sorted(
                instruction.operand
                for instruction in chunk.instructions
                if instruction.opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE)
            )

            def no_jump_enters_middle(start: int, end: int) -> bool:
                target_index = bisect_right(jump_targets, start)
                return (
                    target_index >= len(jump_targets)
                    or jump_targets[target_index] > end
                )

            nodes: list[_Node] = []
            active: list[int] = []

            for index, instruction in enumerate(chunk.instructions):
                opcode = instruction.opcode

                if opcode in _UNARY_OPS and active:
                    previous_position = active[-1]
                    previous = nodes[previous_position]
                    if (
                        previous.instruction is not None
                        and previous.instruction.opcode is Opcode.CONSTANT
                        and no_jump_enters_middle(previous.start, index)
                    ):
                        value = _safe_fold(
                            opcode,
                            constants[previous.instruction.operand],
                        )
                        if value is not _UNFOLDABLE:
                            start = previous.start
                            del nodes[previous_position:]
                            nodes.append(
                                _Node(
                                    Instruction(
                                        Opcode.CONSTANT,
                                        intern(value),
                                        instruction.location or previous.instruction.location,
                                    ),
                                    start,
                                    index,
                                )
                            )
                            active[-1] = len(nodes) - 1
                            folded += 1
                            continue

                if opcode in _BINARY_OPS and len(active) >= 2:
                    left_position, right_position = active[-2:]
                    left_node = nodes[left_position]
                    right_node = nodes[right_position]
                    only_removed_nodes_between = all(
                        node.instruction is None
                        for node in nodes[left_position + 1:right_position]
                    )
                    if (
                        only_removed_nodes_between
                        and left_node.instruction is not None
                        and right_node.instruction is not None
                        and left_node.instruction.opcode is Opcode.CONSTANT
                        and right_node.instruction.opcode is Opcode.CONSTANT
                        and no_jump_enters_middle(left_node.start, index)
                    ):
                        value = _safe_fold(
                            opcode,
                            constants[left_node.instruction.operand],
                            constants[right_node.instruction.operand],
                        )
                        if value is not _UNFOLDABLE:
                            start = left_node.start
                            location = (
                                instruction.location
                                or right_node.instruction.location
                                or left_node.instruction.location
                            )
                            del nodes[left_position:]
                            nodes.append(
                                _Node(
                                    Instruction(
                                        Opcode.CONSTANT,
                                        intern(value),
                                        location,
                                    ),
                                    start,
                                    index,
                                )
                            )
                            active[-2:] = [len(nodes) - 1]
                            folded += 1
                            continue

                if opcode is Opcode.POP and active:
                    previous_position = active[-1]
                    previous = nodes[previous_position]
                    if (
                        previous.instruction is not None
                        and previous.instruction.opcode is Opcode.DUP
                        and previous.start not in jump_targets
                        and index not in jump_targets
                    ):
                        start = previous.start
                        del nodes[previous_position:]
                        nodes.append(_Node(None, start, index))
                        active.pop()
                        removed += 2
                        continue

                nodes.append(_Node(instruction, index, index))
                active.append(len(nodes) - 1)

            # Compact each chunk and map every old instruction index to its
            # replacement. Removed DUP/POP ranges map to the next instruction.
            output: list[Instruction] = []
            old_to_new: dict[int, int] = {}
            next_output_index = 0
            for node in nodes:
                if node.instruction is None:
                    for old_index in range(node.start, node.end + 1):
                        old_to_new[old_index] = next_output_index
                    continue
                new_index = len(output)
                output.append(node.instruction)
                for old_index in range(node.start, node.end + 1):
                    old_to_new[old_index] = new_index
                next_output_index = new_index

            # Deleted no-op ranges can occur before later nodes; the map above
            # uses the next surviving index, which is now available from the
            # completed old-index map.
            if any(node.instruction is None for node in nodes):
                for node in nodes:
                    if node.instruction is None:
                        following = next(
                            (
                                old_to_new[candidate.start]
                                for candidate in nodes
                                if candidate.instruction is not None
                                and candidate.start > node.end
                            ),
                            max(0, len(output) - 1),
                        )
                        for old_index in range(node.start, node.end + 1):
                            old_to_new[old_index] = following

            remapped: list[Instruction] = []
            for instruction in output:
                if instruction.opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
                    instruction = replace(
                        instruction,
                        operand=old_to_new[instruction.operand],
                    )
                remapped.append(instruction)

            return CodeChunk(
                name=chunk.name,
                instructions=tuple(remapped),
                local_count=chunk.local_count,
                arity=chunk.arity,
            )

        main = optimize_chunk(module.main)
        functions = tuple(
            BytecodeFunction(
                name=function.name,
                chunk=optimize_chunk(function.chunk),
                parameter_types=function.parameter_types,
                return_type=function.return_type,
            )
            for function in module.functions
        )

        # Keep only referenced constants, in first-use order, and deduplicate
        # by both value and exact type (True must not alias integer 1).
        compact_constants: list[object] = []
        compact_indices: dict[tuple[type, object], int] = {}

        def compact_chunk(chunk: CodeChunk) -> CodeChunk:
            rewritten: list[Instruction] = []
            for instruction in chunk.instructions:
                if instruction.opcode is not Opcode.CONSTANT:
                    rewritten.append(instruction)
                    continue
                value = constants[instruction.operand]
                key = (type(value), value)
                new_index = compact_indices.get(key)
                if new_index is None:
                    new_index = len(compact_constants)
                    compact_indices[key] = new_index
                    compact_constants.append(value)
                rewritten.append(replace(instruction, operand=new_index))
            return CodeChunk(
                name=chunk.name,
                instructions=tuple(rewritten),
                local_count=chunk.local_count,
                arity=chunk.arity,
            )

        compact_main = compact_chunk(main)
        compact_functions = tuple(
            BytecodeFunction(
                name=function.name,
                chunk=compact_chunk(function.chunk),
                parameter_types=function.parameter_types,
                return_type=function.return_type,
            )
            for function in functions
        )
        optimized = BytecodeModule(
            constants=tuple(compact_constants),  # type: ignore[arg-type]
            main=compact_main,
            source_name=module.source_name,
            format_version=module.format_version,
            functions=compact_functions,
            debug_info=module.debug_info,
        )

        final_validation = BytecodeVerifier().verify(optimized)
        if not final_validation.is_valid:
            messages = "; ".join(item.message for item in final_validation.diagnostics[:3])
            raise RuntimeError(f"Optimizer produced invalid bytecode: {messages}")

        original_count = len(module.main.instructions) + sum(
            len(function.chunk.instructions) for function in module.functions
        )
        optimized_count = len(optimized.main.instructions) + sum(
            len(function.chunk.instructions) for function in optimized.functions
        )
        stats = OptimizationStats(
            original_instruction_count=original_count,
            optimized_instruction_count=optimized_count,
            folded_expressions=folded,
            removed_noops=removed,
            constants_before=len(module.constants),
            constants_after=len(optimized.constants),
        )
        return OptimizationResult(optimized, stats)
