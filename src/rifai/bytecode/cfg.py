"""Control-flow graph construction and reachability analysis for bytecode chunks.

The CFG is deliberately a read-only analysis layer: it never mutates instructions,
source maps, stack behavior, or the serialized bytecode format.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rifai.bytecode.chunk import CodeChunk
from rifai.bytecode.instructions import Opcode
from rifai.bytecode.module import BytecodeModule


_TERMINATORS = frozenset({Opcode.JUMP, Opcode.JUMP_IF_FALSE, Opcode.RETURN, Opcode.HALT})


@dataclass(frozen=True, slots=True)
class BasicBlock:
    """A maximal straight-line instruction range with explicit control-flow edges."""

    block_id: int
    start: int
    end: int
    successors: tuple[int, ...]

    @property
    def instruction_count(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True, slots=True)
class ControlFlowGraph:
    """Immutable basic-block graph for one bytecode chunk."""

    chunk_name: str
    entry_block: int | None
    blocks: tuple[BasicBlock, ...]
    reachable_blocks: tuple[int, ...]
    unreachable_blocks: tuple[int, ...]

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def edge_count(self) -> int:
        return sum(len(block.successors) for block in self.blocks)

    @property
    def reachable_instruction_count(self) -> int:
        reachable = set(self.reachable_blocks)
        return sum(block.instruction_count for block in self.blocks if block.block_id in reachable)

    @property
    def unreachable_instruction_count(self) -> int:
        unreachable = set(self.unreachable_blocks)
        return sum(block.instruction_count for block in self.blocks if block.block_id in unreachable)

    def as_dict(self) -> dict[str, object]:
        """Return a stable JSON-friendly representation for tooling and reports."""
        return {
            "chunk": self.chunk_name,
            "entry": self.entry_block,
            "block_count": self.block_count,
            "edge_count": self.edge_count,
            "reachable_blocks": list(self.reachable_blocks),
            "unreachable_blocks": list(self.unreachable_blocks),
            "reachable_instruction_count": self.reachable_instruction_count,
            "unreachable_instruction_count": self.unreachable_instruction_count,
            "blocks": [
                {
                    "id": block.block_id,
                    "start": block.start,
                    "end": block.end,
                    "instruction_count": block.instruction_count,
                    "successors": list(block.successors),
                    "reachable": block.block_id in self.reachable_blocks,
                }
                for block in self.blocks
            ],
        }


def build_control_flow_graph(chunk: CodeChunk) -> ControlFlowGraph:
    """Split a verified code chunk into basic blocks and compute reachability.

    Block IDs are their first instruction offsets, which makes reports stable
    and lets editor/debugger clients map blocks back to bytecode directly.
    """
    if not isinstance(chunk, CodeChunk):
        raise TypeError("chunk must be a CodeChunk.")

    instructions = chunk.instructions
    count = len(instructions)
    if count == 0:
        return ControlFlowGraph(chunk.name, None, (), (), ())

    leaders = {0}
    for index, instruction in enumerate(instructions):
        if instruction.opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
            target = instruction.operand
            if type(target) is not int or not 0 <= target < count:
                raise ValueError(f"Invalid jump target {target!r} at instruction {index}.")
            leaders.add(target)
        if instruction.opcode in _TERMINATORS and index + 1 < count:
            leaders.add(index + 1)

    starts = sorted(leaders)
    ranges = [
        (start, (starts[position + 1] - 1) if position + 1 < len(starts) else count - 1)
        for position, start in enumerate(starts)
    ]
    block_for_instruction: dict[int, int] = {}
    for start, end in ranges:
        for index in range(start, end + 1):
            block_for_instruction[index] = start

    blocks: list[BasicBlock] = []
    for start, end in ranges:
        last = instructions[end]
        successors: list[int] = []
        if last.opcode is Opcode.JUMP:
            successors.append(block_for_instruction[last.operand])
        elif last.opcode is Opcode.JUMP_IF_FALSE:
            successors.append(block_for_instruction[last.operand])
            if end + 1 < count:
                fallthrough = block_for_instruction[end + 1]
                if fallthrough not in successors:
                    successors.append(fallthrough)
        elif last.opcode not in (Opcode.RETURN, Opcode.HALT) and end + 1 < count:
            successors.append(block_for_instruction[end + 1])
        blocks.append(BasicBlock(start, start, end, tuple(successors)))

    by_id = {block.block_id: block for block in blocks}
    visited: set[int] = set()
    pending = deque([starts[0]])
    while pending:
        block_id = pending.popleft()
        if block_id in visited:
            continue
        visited.add(block_id)
        pending.extend(
            successor
            for successor in by_id[block_id].successors
            if successor not in visited
        )

    reachable = tuple(start for start in starts if start in visited)
    unreachable = tuple(start for start in starts if start not in visited)
    return ControlFlowGraph(chunk.name, starts[0], tuple(blocks), reachable, unreachable)


def analyze_module_control_flow(module: BytecodeModule) -> dict[str, ControlFlowGraph]:
    """Build CFGs for the entry chunk and every function in declaration order."""
    if not isinstance(module, BytecodeModule):
        raise TypeError("module must be a BytecodeModule.")
    result = {"<main>": build_control_flow_graph(module.main)}
    for function in module.functions:
        if function.name in result:
            raise ValueError(f"Duplicate bytecode chunk name {function.name!r}.")
        result[function.name] = build_control_flow_graph(function.chunk)
    return result
