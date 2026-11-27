"""Structural verifier for Rifa'i's explicit-value intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.instructions import Opcode, SourceLocation
from rifai.bytecode.module import is_constant
from rifai.ir.model import (
    IRBranch, IRFunction, IRHalt, IRJump, IRModule, IROperation, IRReturn,
    IRValue,
)


_TERMINATORS = frozenset({Opcode.JUMP, Opcode.JUMP_IF_FALSE, Opcode.RETURN, Opcode.HALT})
_ARRAY_NEW = frozenset({
    Opcode.ARRAY_NEW_INT, Opcode.ARRAY_NEW_FLOAT,
    Opcode.ARRAY_NEW_BOOL, Opcode.ARRAY_NEW_STRING,
})
_UNARY = frozenset({Opcode.NEGATE, Opcode.NOT})
_BINARY = frozenset({
    Opcode.ADD, Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE, Opcode.MODULO,
    Opcode.EQUAL, Opcode.NOT_EQUAL, Opcode.LESS, Opcode.LESS_EQUAL,
    Opcode.GREATER, Opcode.GREATER_EQUAL, Opcode.AND, Opcode.OR,
})


@dataclass(frozen=True, slots=True)
class IRValidationResult:
    diagnostics: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


class IRVerifier:
    """Validate IR definitions, operation contracts, block edges, and signatures."""

    def verify(self, module: IRModule) -> IRValidationResult:
        errors: list[str] = []

        def report(message: str) -> None:
            errors.append(message)

        if not isinstance(module, IRModule):
            return IRValidationResult(("Expected an IRModule instance.",))
        if module.ir_version != 1:
            report(f"Unsupported IR version {module.ir_version!r}.")
        if not isinstance(module.constants, tuple) or any(
            not is_constant(value) for value in module.constants
        ):
            report("IR constant pool must contain supported immutable constants.")
        if not isinstance(module.main, IRFunction) or module.main.name != "<main>":
            report("IR main function must be named '<main>'.")
            return IRValidationResult(tuple(errors))

        functions: dict[str, IRFunction] = {}
        for function in module.functions:
            if not isinstance(function, IRFunction):
                report("IR function table contains an invalid function.")
                continue
            if not isinstance(function.name, str) or not function.name or function.name == "<main>":
                report("IR function names must be non-empty and cannot be '<main>'.")
                continue
            if function.name in functions:
                report(f"Duplicate IR function '{function.name}'.")
            else:
                functions[function.name] = function

        self._verify_function(module, module.main, functions, errors)
        for function in module.functions:
            if isinstance(function, IRFunction):
                self._verify_function(module, function, functions, errors)
        return IRValidationResult(tuple(errors))

    def _verify_function(
        self,
        module: IRModule,
        function: IRFunction,
        functions: dict[str, IRFunction],
        errors: list[str],
    ) -> None:
        def report(message: str) -> None:
            errors.append(f"{function.name}: {message}")

        if type(function.local_count) is not int or function.local_count < 0:
            report("local_count must be a non-negative integer.")
        if type(function.arity) is not int or function.arity < 0 or function.arity > function.local_count:
            report("arity must be non-negative and cannot exceed local_count.")
        if len(function.parameter_types) != function.arity:
            report("parameter_types length does not match arity.")
        if not function.blocks:
            report("function must contain at least one basic block.")
            return

        block_map = {block.block_id: block for block in function.blocks}
        if len(block_map) != len(function.blocks):
            report("basic block identifiers must be unique.")
            return
        if function.blocks[0].block_id != 0:
            report("the entry block must have identifier 0.")
        definitions: set[int] = set()
        definition_types: dict[int, str | None] = {}
        edges: list[tuple[int, tuple[int, ...]]] = []
        branch_edges: list[tuple[int, tuple[int, ...]]] = []

        for block in function.blocks:
            local_definitions: set[int] = set()
            for parameter in block.parameters:
                self._define(parameter, definitions, local_definitions, report)
                if isinstance(parameter, IRValue):
                    definition_types[parameter.value_id] = parameter.type_name
            for operation in block.operations:
                if not isinstance(operation, IROperation):
                    report(f"block {block.block_id} contains an invalid operation.")
                    continue
                if operation.opcode in _TERMINATORS:
                    report(f"block {block.block_id} stores a terminator as an operation.")
                for value_id in operation.inputs:
                    self._use(value_id, local_definitions, report, block.block_id)
                if operation.opcode in (Opcode.LOAD_LOCAL, Opcode.STORE_LOCAL) and (
                    type(operation.operand) is not int
                    or operation.operand < 0
                    or operation.operand >= function.local_count
                ):
                    report(f"{operation.opcode.value} references an out-of-range local slot.")
                expected_inputs, expected_outputs = self._operation_shape(
                    module, operation, functions, report
                )
                if expected_inputs is not None and len(operation.inputs) != expected_inputs:
                    report(
                        f"{operation.opcode.value} in block {block.block_id} expects "
                        f"{expected_inputs} input value(s), found {len(operation.inputs)}."
                    )
                if expected_outputs is not None and len(operation.outputs) != expected_outputs:
                    report(
                        f"{operation.opcode.value} in block {block.block_id} expects "
                        f"{expected_outputs} output value(s), found {len(operation.outputs)}."
                    )
                for output in operation.outputs:
                    self._define(output, definitions, local_definitions, report)
                    if isinstance(output, IRValue):
                        definition_types[output.value_id] = output.type_name
                if operation.location is not None and not isinstance(operation.location, SourceLocation):
                    report(f"operation in block {block.block_id} has invalid source metadata.")

            term = block.terminator
            if isinstance(term, IRJump):
                for value_id in term.arguments:
                    self._use(value_id, local_definitions, report, block.block_id)
                edges.append((term.target, term.arguments))
            elif isinstance(term, IRBranch):
                self._use(term.condition, local_definitions, report, block.block_id)
                for value_id in (*term.false_arguments, *term.true_arguments):
                    self._use(value_id, local_definitions, report, block.block_id)
                edges.append((term.false_target, term.false_arguments))
                edges.append((term.true_target, term.true_arguments))
            elif isinstance(term, IRReturn):
                if function.name == "<main>":
                    report("RETURN is only valid inside a function.")
                if function.return_type == "void" and term.value is not None:
                    report(f"void function returns a value in block {block.block_id}.")
                if function.return_type != "void" and term.value is None:
                    report(f"non-void function has an empty return in block {block.block_id}.")
                if term.value is not None:
                    self._use(term.value, local_definitions, report, block.block_id)
            elif isinstance(term, IRHalt):
                if function.name != "<main>":
                    report("HALT is only valid in the main function.")
            else:
                report(f"block {block.block_id} has an unknown terminator.")

        for block in function.blocks:
            # Bytecode verification intentionally permits stack-inconsistent
            # control flow in unreachable regions; these edges cannot be taken
            # and therefore do not participate in live block-parameter joins.
            if not block.reachable:
                for target in (
                    (block.terminator.target,)
                    if isinstance(block.terminator, IRJump)
                    else (block.terminator.false_target, block.terminator.true_target)
                    if isinstance(block.terminator, IRBranch)
                    else ()
                ):
                    if target not in block_map:
                        report(f"block {block.block_id} targets missing block {target}.")
                continue
            term = block.terminator
            edge_list: tuple[tuple[int, tuple[int, ...]], ...]
            if isinstance(term, IRJump):
                edge_list = ((term.target, term.arguments),)
            elif isinstance(term, IRBranch):
                edge_list = (
                    (term.false_target, term.false_arguments),
                    (term.true_target, term.true_arguments),
                )
            else:
                edge_list = ()
            for target, arguments in edge_list:
                target_block = block_map.get(target)
                if target_block is None:
                    report(f"block {block.block_id} targets missing block {target}.")
                    continue
                if len(arguments) != len(target_block.parameters):
                    report(
                        f"edge {block.block_id}->{target} passes {len(arguments)} value(s), "
                        f"but target expects {len(target_block.parameters)}."
                    )
                else:
                    for argument, parameter in zip(arguments, target_block.parameters):
                        source_type = definition_types.get(argument)
                        if (
                            source_type is not None
                            and parameter.type_name is not None
                            and source_type != parameter.type_name
                        ):
                            report(
                                f"edge {block.block_id}->{target} passes {source_type} "
                                f"to a {parameter.type_name} block parameter."
                            )

        if function.name == "<main>" and not isinstance(function.blocks[-1].terminator, IRHalt):
            report("main must end with HALT.")
        if function.name != "<main>" and not any(
            isinstance(block.terminator, IRReturn) for block in function.blocks
        ):
            report("function must contain at least one RETURN terminator.")

    @staticmethod
    def _define(
        value: IRValue,
        definitions: set[int],
        local_definitions: set[int],
        report,
    ) -> None:
        if not isinstance(value, IRValue) or type(value.value_id) is not int or value.value_id < 0:
            report("IR definitions must have non-negative integer value identifiers.")
            return
        if value.value_id in definitions:
            report(f"virtual value %{value.value_id} is defined more than once.")
            return
        if value.type_name is not None and not isinstance(value.type_name, str):
            report(f"virtual value %{value.value_id} has an invalid type annotation.")
        definitions.add(value.value_id)
        local_definitions.add(value.value_id)

    @staticmethod
    def _use(value_id: int, local_definitions: set[int], report, block_id: int) -> None:
        if type(value_id) is not int or value_id not in local_definitions:
            report(f"block {block_id} uses undefined or non-local virtual value %{value_id}.")

    @staticmethod
    def _operation_shape(module, operation, functions, report):
        opcode = operation.opcode
        if opcode is Opcode.CONSTANT:
            if type(operation.operand) is not int or not 0 <= operation.operand < len(module.constants):
                report("CONSTANT references an invalid IR constant index.")
            return 0, 1
        if opcode in (Opcode.LOAD_LOCAL, Opcode.LOAD_GLOBAL):
            if opcode is Opcode.LOAD_LOCAL and (
                type(operation.operand) is not int or operation.operand < 0
            ):
                report("LOAD_LOCAL has an invalid slot.")
            if opcode is Opcode.LOAD_GLOBAL and not isinstance(operation.operand, str):
                report("LOAD_GLOBAL has an invalid global name.")
            return 0, 1
        if opcode in (Opcode.STORE_LOCAL, Opcode.STORE_GLOBAL):
            if opcode is Opcode.STORE_LOCAL and (
                type(operation.operand) is not int or operation.operand < 0
            ):
                report("STORE_LOCAL has an invalid slot.")
            if opcode is Opcode.STORE_GLOBAL and not isinstance(operation.operand, str):
                report("STORE_GLOBAL has an invalid global name.")
            return 1, 0
        if opcode is Opcode.DUP:
            return 1, 1
        if opcode in _UNARY:
            return 1, 1
        if opcode in _BINARY:
            return 2, 1
        if opcode in (Opcode.POP, Opcode.PRINT):
            return 1, 0
        if opcode in _ARRAY_NEW:
            if type(operation.operand) is not int or operation.operand < 0:
                report("array constructor has an invalid element count.")
            return operation.operand if type(operation.operand) is int and operation.operand >= 0 else None, 1
        if opcode is Opcode.ARRAY_GET:
            return 2, 1
        if opcode is Opcode.ARRAY_SET:
            return 3, 0
        if opcode is Opcode.LENGTH:
            return 1, 1
        if opcode is Opcode.ARRAY_PUSH:
            return 2, 0
        if opcode is Opcode.ARRAY_POP:
            return 1, 1
        if opcode is Opcode.CALL:
            target = functions.get(operation.operand) if isinstance(operation.operand, str) else None
            if target is None:
                report(f"CALL references unknown function {operation.operand!r}.")
                return None, None
            return target.arity, 1 if target.return_type != "void" else 0
        report(f"unsupported IR operation {opcode!r}.")
        return None, None
