"""IR control-flow analysis: predecessors, dominators, and loop back-edges."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rifai.ir.model import IRBranch, IRFunction, IRJump, IRModule


def _successors(block) -> tuple[int, ...]:
    term = block.terminator
    if isinstance(term, IRJump):
        return (term.target,)
    if isinstance(term, IRBranch):
        return (term.false_target, term.true_target) if term.false_target != term.true_target else (term.false_target,)
    return ()


@dataclass(frozen=True, slots=True)
class IRFunctionAnalysis:
    name: str
    reachable_blocks: tuple[int, ...]
    unreachable_blocks: tuple[int, ...]
    predecessors: tuple[tuple[int, tuple[int, ...]], ...]
    dominators: tuple[tuple[int, tuple[int, ...]], ...]
    immediate_dominators: tuple[tuple[int, int | None], ...]
    loop_back_edges: tuple[tuple[int, int], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "reachable_blocks": list(self.reachable_blocks),
            "unreachable_blocks": list(self.unreachable_blocks),
            "predecessors": {str(key): list(value) for key, value in self.predecessors},
            "dominators": {str(key): list(value) for key, value in self.dominators},
            "immediate_dominators": {str(key): value for key, value in self.immediate_dominators},
            "loop_back_edges": [
                {"source": source, "target": target}
                for source, target in self.loop_back_edges
            ],
        }


@dataclass(frozen=True, slots=True)
class IRAnalysis:
    functions: tuple[IRFunctionAnalysis, ...]
    function_count: int
    block_count: int
    operation_count: int
    value_count: int
    edge_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "function_count": self.function_count,
            "block_count": self.block_count,
            "operation_count": self.operation_count,
            "value_count": self.value_count,
            "edge_count": self.edge_count,
            "functions": {
                item.name: item.as_dict() for item in self.functions
            },
        }


class IRAnalyzer:
    """Compute deterministic reachability, dominators, and natural back-edges."""

    def analyze(self, module: IRModule) -> IRAnalysis:
        if not isinstance(module, IRModule):
            raise TypeError("module must be an IRModule.")
        functions = tuple(
            self._analyze_function(function)
            for function in (module.main, *module.functions)
        )
        return IRAnalysis(
            functions=functions,
            function_count=1 + len(module.functions),
            block_count=module.block_count,
            operation_count=module.operation_count,
            value_count=module.value_count,
            edge_count=sum(
                len(_successors(block))
                for function in (module.main, *module.functions)
                for block in function.blocks
            ),
        )

    @staticmethod
    def _analyze_function(function: IRFunction) -> IRFunctionAnalysis:
        by_id = {block.block_id: block for block in function.blocks}
        entry = function.blocks[0].block_id
        predecessors: dict[int, list[int]] = {block_id: [] for block_id in by_id}
        for block in function.blocks:
            for successor in _successors(block):
                if successor in predecessors:
                    predecessors[successor].append(block.block_id)

        visited: set[int] = set()
        pending = deque([entry])
        while pending:
            block_id = pending.popleft()
            if block_id in visited or block_id not in by_id:
                continue
            visited.add(block_id)
            pending.extend(_successors(by_id[block_id]))

        reachable = tuple(block.block_id for block in function.blocks if block.block_id in visited)
        unreachable = tuple(block.block_id for block in function.blocks if block.block_id not in visited)
        dominators: dict[int, set[int]] = {
            block_id: ({block_id} if block_id == entry else set(visited))
            for block_id in visited
        }
        changed = True
        while changed:
            changed = False
            for block_id in reachable:
                if block_id == entry:
                    continue
                incoming = [
                    predecessor
                    for predecessor in predecessors[block_id]
                    if predecessor in visited
                ]
                common = (
                    set.intersection(*(dominators[item] for item in incoming))
                    if incoming else set()
                )
                updated = common | {block_id}
                if updated != dominators[block_id]:
                    dominators[block_id] = updated
                    changed = True

        immediate: dict[int, int | None] = {entry: None}
        for block_id in reachable:
            if block_id == entry:
                continue
            strict = dominators[block_id] - {block_id}
            immediate[block_id] = (
                max(strict, key=lambda item: len(dominators[item]))
                if strict else None
            )
        back_edges = tuple(
            (block.block_id, successor)
            for block in function.blocks if block.block_id in visited
            for successor in _successors(block)
            if successor in dominators.get(block.block_id, set())
        )
        return IRFunctionAnalysis(
            name=function.name,
            reachable_blocks=reachable,
            unreachable_blocks=unreachable,
            predecessors=tuple(
                (block_id, tuple(sorted(predecessors[block_id])))
                for block_id in by_id
            ),
            dominators=tuple(
                (block_id, tuple(sorted(dominators[block_id])))
                for block_id in reachable
            ),
            immediate_dominators=tuple(
                (block_id, immediate.get(block_id))
                for block_id in reachable
            ),
            loop_back_edges=back_edges,
        )
