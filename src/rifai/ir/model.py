"""Immutable, typed, stack-to-SSA intermediate representation models.

IR is independent of the serialized bytecode container. Operand-stack values
become explicit virtual values; stack merges become block parameters, while
locals/globals remain explicit memory operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from rifai.bytecode.instructions import Opcode, SourceLocation
from rifai.bytecode.module import BytecodeDebugInfo


@dataclass(frozen=True, slots=True)
class IRValue:
    """A typed virtual value defined once by a block parameter or operation."""

    value_id: int
    type_name: str | None = None


@dataclass(frozen=True, slots=True)
class IROperation:
    """One non-terminating IR operation with explicit virtual-value operands."""

    opcode: Opcode
    outputs: tuple[IRValue, ...]
    inputs: tuple[int, ...]
    operand: int | str | None = None
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "inputs", tuple(self.inputs))


@dataclass(frozen=True, slots=True)
class IRJump:
    """Unconditional edge carrying the outgoing operand-stack values."""

    target: int
    arguments: tuple[int, ...]
    fallthrough: bool = False
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))


@dataclass(frozen=True, slots=True)
class IRBranch:
    """Conditional edges; false_target corresponds to JUMP_IF_FALSE."""

    condition: int
    false_target: int
    true_target: int
    false_arguments: tuple[int, ...]
    true_arguments: tuple[int, ...]
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "false_arguments", tuple(self.false_arguments))
        object.__setattr__(self, "true_arguments", tuple(self.true_arguments))


@dataclass(frozen=True, slots=True)
class IRReturn:
    """Function return with an optional result value."""

    value: int | None = None
    location: SourceLocation | None = None


@dataclass(frozen=True, slots=True)
class IRHalt:
    """Main-program termination."""

    location: SourceLocation | None = None


IRTerminator: TypeAlias = IRJump | IRBranch | IRReturn | IRHalt


@dataclass(frozen=True, slots=True)
class IRBlock:
    """A basic block with SSA-like block parameters and explicit terminator."""

    block_id: int
    parameters: tuple[IRValue, ...]
    operations: tuple[IROperation, ...]
    terminator: IRTerminator
    source_start: int
    source_end: int
    reachable: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "operations", tuple(self.operations))


@dataclass(frozen=True, slots=True)
class IRLocal:
    """Source/debug metadata for a VM local slot."""

    slot: int
    name: str
    type_name: str


@dataclass(frozen=True, slots=True)
class IRFunction:
    """IR body and source-level signature for one compiled function or main."""

    name: str
    blocks: tuple[IRBlock, ...]
    local_count: int
    arity: int
    parameter_types: tuple[str, ...] = ()
    return_type: str = "void"
    local_symbols: tuple[IRLocal, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "parameter_types", tuple(self.parameter_types))
        object.__setattr__(self, "local_symbols", tuple(self.local_symbols))


@dataclass(frozen=True, slots=True)
class IRModule:
    """Target-independent compiler IR plus constants and source/debug context."""

    constants: tuple[int | float | bool | str, ...]
    main: IRFunction
    functions: tuple[IRFunction, ...] = ()
    source_name: str | None = None
    format_version: int = 4
    debug_info: BytecodeDebugInfo | None = None
    ir_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "constants", tuple(self.constants))
        object.__setattr__(self, "functions", tuple(self.functions))

    def functions_by_name(self) -> dict[str, IRFunction]:
        return {function.name: function for function in self.functions}

    @property
    def operation_count(self) -> int:
        return sum(
            len(block.operations)
            for function in (self.main, *self.functions)
            for block in function.blocks
        )

    @property
    def block_count(self) -> int:
        return sum(len(function.blocks) for function in (self.main, *self.functions))

    @property
    def value_count(self) -> int:
        return sum(
            len(block.parameters) + sum(len(operation.outputs) for operation in block.operations)
            for function in (self.main, *self.functions)
            for block in function.blocks
        )

    @property
    def edge_count(self) -> int:
        return sum(
            1 if isinstance(block.terminator, IRJump)
            else (
                1 if block.terminator.false_target == block.terminator.true_target else 2
            ) if isinstance(block.terminator, IRBranch)
            else 0
            for function in (self.main, *self.functions)
            for block in function.blocks
        )

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-friendly IR representation."""
        def value_data(value: IRValue) -> dict[str, object]:
            return {"id": value.value_id, "type": value.type_name}

        def terminator_data(term: IRTerminator) -> dict[str, object]:
            if isinstance(term, IRJump):
                return {
                    "kind": "fallthrough" if term.fallthrough else "jump",
                    "target": term.target,
                    "arguments": list(term.arguments),
                }
            if isinstance(term, IRBranch):
                return {
                    "kind": "branch",
                    "condition": term.condition,
                    "false_target": term.false_target,
                    "false_arguments": list(term.false_arguments),
                    "true_target": term.true_target,
                    "true_arguments": list(term.true_arguments),
                }
            if isinstance(term, IRReturn):
                return {"kind": "return", "value": term.value}
            return {"kind": "halt"}

        def function_data(function: IRFunction) -> dict[str, object]:
            return {
                "name": function.name,
                "parameter_types": list(function.parameter_types),
                "return_type": function.return_type,
                "local_count": function.local_count,
                "arity": function.arity,
                "locals": [
                    {"slot": item.slot, "name": item.name, "type": item.type_name}
                    for item in function.local_symbols
                ],
                "blocks": [
                    {
                        "id": block.block_id,
                        "source_range": [block.source_start, block.source_end],
                        "reachable": block.reachable,
                        "parameters": [value_data(item) for item in block.parameters],
                        "operations": [
                            {
                                "opcode": operation.opcode.value,
                                "outputs": [value_data(item) for item in operation.outputs],
                                "inputs": list(operation.inputs),
                                "operand": operation.operand,
                                "source": None if operation.location is None else {
                                    "line": operation.location.line,
                                    "column": operation.location.column,
                                },
                            }
                            for operation in block.operations
                        ],
                        "terminator": terminator_data(block.terminator),
                    }
                    for block in function.blocks
                ],
            }

        return {
            "ir_version": self.ir_version,
            "format_version": self.format_version,
            "source_name": self.source_name,
            "constants": [
                {"index": index, "type": type(value).__name__, "value": value}
                for index, value in enumerate(self.constants)
            ],
            "stats": {
                "functions": len(self.functions),
                "blocks": self.block_count,
                "operations": self.operation_count,
                "values": self.value_count,
                "edges": self.edge_count,
            },
            "main": function_data(self.main),
            "functions": [function_data(function) for function in self.functions],
        }
