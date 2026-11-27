"""Deterministic multi-pass pipeline for Rifa'i intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from rifai.ir.analysis import IRAnalysis, IRAnalyzer
from rifai.ir.model import (
    IRBranch, IRFunction, IRHalt, IRJump, IRModule, IROperation,
    IRReturn, IRValue,
)
from rifai.ir.verifier import IRVerifier


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


@dataclass(frozen=True, slots=True)
class IRPassResult:
    module: IRModule
    analysis: IRAnalysis
    stats: IRPassStats


class IRValueNumberingPass:
    """Canonicalize virtual value IDs in deterministic block/instruction order."""

    name = "canonical-value-numbering"

    def run(self, module: IRModule) -> tuple[IRModule, int]:
        functions = tuple(self._run_function(function) for function in (module.main, *module.functions))
        return (
            replace(module, main=functions[0], functions=functions[1:]),
            module.value_count,
        )

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
                operations.append(
                    replace(operation, inputs=inputs, outputs=tuple(outputs))
                )

            term = block.terminator
            if isinstance(term, IRJump):
                term = replace(
                    term,
                    arguments=tuple(mapping[value_id] for value_id in term.arguments),
                )
            elif isinstance(term, IRBranch):
                term = replace(
                    term,
                    condition=mapping[term.condition],
                    false_arguments=tuple(mapping[value_id] for value_id in term.false_arguments),
                    true_arguments=tuple(mapping[value_id] for value_id in term.true_arguments),
                )
            elif isinstance(term, IRReturn) and term.value is not None:
                term = replace(term, value=mapping[term.value])
            blocks.append(
                replace(
                    block,
                    parameters=tuple(parameters),
                    operations=tuple(operations),
                    terminator=term,
                )
            )
        return replace(function, blocks=tuple(blocks))


class IRPassManager:
    """Run validation, canonicalization, and structural analyses in fixed order."""

    def __init__(self) -> None:
        self.verifier = IRVerifier()
        self.numbering = IRValueNumberingPass()
        self.analyzer = IRAnalyzer()

    def run(self, module: IRModule) -> IRPassResult:
        initial = self.verifier.verify(module)
        if not initial.is_valid:
            raise ValueError("IR verification failed: " + "; ".join(initial.diagnostics[:5]))

        normalized, renumbered = self.numbering.run(module)
        final = self.verifier.verify(normalized)
        if not final.is_valid:
            raise RuntimeError(
                "IR pass pipeline produced invalid IR: " + "; ".join(final.diagnostics[:5])
            )

        analysis = self.analyzer.analyze(normalized)
        stats = IRPassStats(
            passes=(
                "verify-input",
                self.numbering.name,
                "verify-output",
                "cfg-dominator-analysis",
            ),
            function_count=analysis.function_count,
            block_count=analysis.block_count,
            operation_count=analysis.operation_count,
            value_count=analysis.value_count,
            edge_count=analysis.edge_count,
            loop_back_edge_count=sum(len(item.loop_back_edges) for item in analysis.functions),
            renumbered_values=renumbered,
        )
        return IRPassResult(normalized, analysis, stats)
