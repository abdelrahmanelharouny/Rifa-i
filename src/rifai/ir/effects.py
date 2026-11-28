"""Conservative effect classification for IR optimization.

The optimizer distinguishes memory effects, observable effects, potentially
trapping operations, and total/speculatable operations. This keeps global
value reuse and loop motion separate from the more permissive notion of
operations that merely do not write memory.
"""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.instructions import Opcode
from rifai.ir.model import IROperation, IRModule


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
        Opcode.FIELD_SET,
    })
    _OBSERVABLE = frozenset({
        Opcode.STORE_LOCAL,
        Opcode.STORE_GLOBAL,
        Opcode.ARRAY_SET,
        Opcode.ARRAY_PUSH,
        Opcode.ARRAY_POP,
        Opcode.FIELD_SET,
        Opcode.CALL,
        Opcode.PRINT,
    })
    _READS_MEMORY = frozenset({
        Opcode.LOAD_LOCAL,
        Opcode.LOAD_GLOBAL,
        Opcode.ARRAY_GET,
        Opcode.LENGTH,
        Opcode.FIELD_GET,
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
        Opcode.STRUCT_NEW,
        Opcode.FIELD_GET,
        Opcode.FIELD_SET,
        Opcode.ENUM_NEW,
        Opcode.ENUM_NEW_PAYLOAD,
        Opcode.ENUM_GET,
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
        Opcode.ENUM_IS,
    })
    # Reuse is safe for deterministic operations over immutable SSA values.
    # Arithmetic may trap, but a dominating first evaluation would already
    # have raised the same fault before any later common use could be reached.
    _COMMONABLE = frozenset({
        Opcode.CONSTANT,
        Opcode.LOAD_LOCAL,
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


    @staticmethod
    def is_speculatable(
        operation: IROperation,
        value_types: dict[int, str | None],
    ) -> bool:
        """Require complete, valid static input types before moving an op."""
        if operation.opcode is Opcode.CONSTANT:
            return not operation.inputs
        input_types = tuple(value_types.get(item) for item in operation.inputs)
        if not input_types or any(item is None for item in input_types):
            return False
        if operation.opcode is Opcode.NOT:
            return input_types == ("bool",)
        if operation.opcode is Opcode.ENUM_IS:
            return len(input_types) == 1 and input_types[0] == operation.operand.split("|", 1)[0]
        if operation.opcode in (Opcode.AND, Opcode.OR):
            return input_types == ("bool", "bool")
        if operation.opcode in (Opcode.EQUAL, Opcode.NOT_EQUAL):
            return (
                len(input_types) == 2
                and input_types[0] == input_types[1]
                and input_types[0] in ("int", "float", "bool", "string")
            )
        if operation.opcode in (
            Opcode.LESS, Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL,
        ):
            return (
                len(input_types) == 2
                and input_types[0] == input_types[1]
                and input_types[0] in ("int", "float")
            )
        return False

    @classmethod
    def is_removable_if_dead(
        cls,
        operation: IROperation,
        value_types: dict[int, str | None],
    ) -> bool:
        """A dead result is removable only when its operation is total."""
        return (
            cls().effects(operation.opcode).removable_if_dead
            and cls.is_speculatable(operation, value_types)
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
