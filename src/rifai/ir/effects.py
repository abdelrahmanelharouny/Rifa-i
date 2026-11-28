"""Conservative effect classification for IR optimization.

The optimizer distinguishes memory effects, observable effects, potentially
trapping operations, and total/speculatable operations. This keeps global
value reuse and loop motion separate from the more permissive notion of
operations that merely do not write memory.
"""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.instructions import Opcode
from rifai.ir.model import IRModule


@dataclass(frozen=True, slots=True)
class IROperationEffects:
    side_effecting: bool
    reads_memory: bool
    writes_memory: bool
    may_trap: bool
    speculatable: bool
    removable_if_dead: bool
    commonable: bool


@dataclass(frozen=True, slots=True)
class IRSideEffectSummary:
    operation_count: int
    side_effecting_operations: int
    memory_reads: int
    memory_writes: int
    potentially_trapping_operations: int
    speculatable_operations: int


class IRSideEffectAnalysis:
    """Classify the effects of Rifa'i IR operations conservatively."""

    _WRITES_MEMORY = frozenset({
        Opcode.STORE_LOCAL,
        Opcode.STORE_GLOBAL,
        Opcode.ARRAY_SET,
        Opcode.ARRAY_PUSH,
        Opcode.ARRAY_POP,
    })
    _OBSERVABLE = frozenset({
        Opcode.STORE_LOCAL,
        Opcode.STORE_GLOBAL,
        Opcode.ARRAY_SET,
        Opcode.ARRAY_PUSH,
        Opcode.ARRAY_POP,
        Opcode.CALL,
        Opcode.PRINT,
    })
    _READS_MEMORY = frozenset({
        Opcode.LOAD_LOCAL,
        Opcode.LOAD_GLOBAL,
        Opcode.ARRAY_GET,
        Opcode.LENGTH,
    })
    _MAY_TRAP = frozenset({
        Opcode.LOAD_LOCAL,
        Opcode.LOAD_GLOBAL,
        Opcode.ARRAY_NEW_INT,
        Opcode.ARRAY_NEW_FLOAT,
        Opcode.ARRAY_NEW_BOOL,
        Opcode.ARRAY_NEW_STRING,
        Opcode.ARRAY_GET,
        Opcode.ARRAY_SET,
        Opcode.LENGTH,
        Opcode.ARRAY_PUSH,
        Opcode.ARRAY_POP,
        Opcode.CALL,
        Opcode.ADD,
        Opcode.SUBTRACT,
        Opcode.MULTIPLY,
        Opcode.DIVIDE,
        Opcode.MODULO,
        Opcode.NEGATE,
    })
    # This subset is total once its input types have passed IR verification.
    # It can be speculated into a loop preheader without moving a runtime fault.
    _SPECULATABLE = frozenset({
        Opcode.CONSTANT,
        Opcode.NOT,
        Opcode.EQUAL,
        Opcode.NOT_EQUAL,
        Opcode.LESS,
        Opcode.LESS_EQUAL,
        Opcode.GREATER,
        Opcode.GREATER_EQUAL,
        Opcode.AND,
        Opcode.OR,
    })
    # Reuse is safe for deterministic operations over immutable SSA values.
    # Arithmetic may trap, but a dominating first evaluation would already
    # have raised the same fault before any later common use could be reached.
    _COMMONABLE = frozenset({
        Opcode.CONSTANT,
        Opcode.NEGATE,
        Opcode.NOT,
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
    })
    _REMOVABLE_IF_DEAD = _SPECULATABLE

    def effects(self, opcode: Opcode) -> IROperationEffects:
        """Return the conservative effect contract for an opcode."""
        writes = opcode in self._WRITES_MEMORY
        reads = opcode in self._READS_MEMORY
        trap = opcode in self._MAY_TRAP
        side_effecting = opcode in self._OBSERVABLE
        speculatable = opcode in self._SPECULATABLE
        return IROperationEffects(
            side_effecting=side_effecting,
            reads_memory=reads,
            writes_memory=writes,
            may_trap=trap,
            speculatable=speculatable,
            removable_if_dead=opcode in self._REMOVABLE_IF_DEAD,
            commonable=opcode in self._COMMONABLE,
        )

    def analyze(self, module: IRModule) -> IRSideEffectSummary:
        """Aggregate effect information across all functions in a module."""
        operations = [
            operation
            for function in (module.main, *module.functions)
            for block in function.blocks
            for operation in block.operations
        ]
        classified = [self.effects(item.opcode) for item in operations]
        return IRSideEffectSummary(
            operation_count=len(operations),
            side_effecting_operations=sum(item.side_effecting for item in classified),
            memory_reads=sum(item.reads_memory for item in classified),
            memory_writes=sum(item.writes_memory for item in classified),
            potentially_trapping_operations=sum(item.may_trap for item in classified),
            speculatable_operations=sum(item.speculatable for item in classified),
        )
