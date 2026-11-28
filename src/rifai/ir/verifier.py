"""Structural verifier for Rifa'i's explicit-value intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.bytecode.instructions import Opcode, SourceLocation
from rifai.bytecode.module import is_constant
from rifai.ir.analysis import IRAnalyzer
from rifai.stdlib import BUILTIN_ARITIES
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
        dominator_info = IRAnalyzer()._analyze_function(function)
        reachable_blocks = set(dominator_info.reachable_blocks)
        dominators = {
            block_id: set(items)
            for block_id, items in dominator_info.dominators
        }
        value_types: dict[int, str | None] = {}
        for candidate_block in function.blocks:
            for parameter in candidate_block.parameters:
                if isinstance(parameter, IRValue):
                    value_types[parameter.value_id] = parameter.type_name
            for candidate_operation in candidate_block.operations:
                if isinstance(candidate_operation, IROperation):
                    for output in candidate_operation.outputs:
                        if isinstance(output, IRValue):
                            value_types[output.value_id] = output.type_name

        definition_locations: dict[int, tuple[int, int]] = {}
        use_sites: list[tuple[int, int, int]] = []

        def record_use(value_id: int, block_id: int, instruction_index: int) -> None:
            use_sites.append((value_id, block_id, instruction_index))

        definition_types: dict[int, str | None] = {}
        local_types = {
            item.slot: item.type_name
            for item in function.local_symbols
            if hasattr(item, "slot") and hasattr(item, "type_name")
        }
        edges: list[tuple[int, tuple[int, ...]]] = []
        branch_edges: list[tuple[int, tuple[int, ...]]] = []

        for block in function.blocks:
            local_definitions: set[int] = set()
            for parameter in block.parameters:
                self._define(parameter, definitions, local_definitions, report)
                if isinstance(parameter, IRValue):
                    definition_types[parameter.value_id] = parameter.type_name
                    definition_locations[parameter.value_id] = (block.block_id, -1)
            for operation_index, operation in enumerate(block.operations):
                if not isinstance(operation, IROperation):
                    report(f"block {block.block_id} contains an invalid operation.")
                    continue
                if operation.opcode in _TERMINATORS:
                    report(f"block {block.block_id} stores a terminator as an operation.")
                for value_id in operation.inputs:
                    record_use(value_id, block.block_id, operation_index)
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
                self._verify_operation_types(
                    module,
                    operation,
                    tuple(value_types.get(value_id) for value_id in operation.inputs),
                    local_types,
                    functions,
                    report,
                    block.block_id,
                )
                for output in operation.outputs:
                    self._define(output, definitions, local_definitions, report)
                    if isinstance(output, IRValue):
                        definition_types[output.value_id] = output.type_name
                        definition_locations[output.value_id] = (block.block_id, operation_index)
                if operation.location is not None and not isinstance(operation.location, SourceLocation):
                    report(f"operation in block {block.block_id} has invalid source metadata.")

            term = block.terminator
            if isinstance(term, IRJump):
                for value_id in term.arguments:
                    record_use(value_id, block.block_id, len(block.operations))
                edges.append((term.target, term.arguments))
            elif isinstance(term, IRBranch):
                record_use(term.condition, block.block_id, len(block.operations))
                for value_id in (*term.false_arguments, *term.true_arguments):
                    record_use(value_id, block.block_id, len(block.operations))
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
                    record_use(term.value, block.block_id, len(block.operations))
                    actual_type = value_types.get(term.value)
                    if actual_type is not None and actual_type != function.return_type:
                        report(
                            f"return value has type {actual_type}, expected {function.return_type}."
                        )
            elif isinstance(term, IRHalt):
                if function.name != "<main>":
                    report("HALT is only valid in the main function.")
            else:
                report(f"block {block.block_id} has an unknown terminator.")

        for value_id, use_block, use_index in use_sites:
            definition = definition_locations.get(value_id)
            if type(value_id) is not int or definition is None:
                report(f"block {use_block} uses undefined virtual value %{value_id}.")
                continue
            definition_block, definition_index = definition
            if definition_block == use_block:
                if definition_index >= use_index:
                    report(
                        f"block {use_block} uses virtual value %{value_id} before its definition."
                    )
            elif use_block in reachable_blocks:
                if definition_block not in dominators.get(use_block, set()):
                    report(
                        f"block {use_block} uses virtual value %{value_id} "
                        f"from non-dominating block {definition_block}."
                    )
            else:
                report(
                    f"unreachable block {use_block} uses non-local virtual value "
                    f"%{value_id} from block {definition_block}."
                )

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
                        source_type = value_types.get(argument)
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
    def _verify_operation_types(
        module,
        operation,
        input_types,
        local_types,
        functions,
        report,
        block_id,
    ) -> None:
        opcode = operation.opcode
        output_types = [value.type_name for value in operation.outputs]
        known = all(value is not None for value in input_types)
        scalar_numeric = {"int", "float"}
        array_element = {
            Opcode.ARRAY_NEW_INT: "int",
            Opcode.ARRAY_NEW_FLOAT: "float",
            Opcode.ARRAY_NEW_BOOL: "bool",
            Opcode.ARRAY_NEW_STRING: "string",
        }

        def check_output(expected: str | None) -> None:
            if expected is not None and output_types and output_types[0] not in (None, expected):
                report(
                    f"{opcode.value} in block {block_id} produces {output_types[0]}, "
                    f"expected {expected}."
                )

        def check_input(index: int, expected: str | None) -> None:
            if expected is not None and index < len(input_types):
                actual = input_types[index]
                if actual is not None and actual != expected:
                    report(
                        f"{opcode.value} in block {block_id} expects {expected} input, "
                        f"found {actual}."
                    )

        if opcode is Opcode.CONSTANT:
            if type(operation.operand) is int and 0 <= operation.operand < len(module.constants):
                value = module.constants[operation.operand]
                expected = (
                    "bool" if type(value) is bool else
                    "int" if type(value) is int else
                    "float" if type(value) is float else
                    "string" if isinstance(value, str) else None
                )
                check_output(expected)
        elif opcode is Opcode.LOAD_LOCAL:
            check_output(local_types.get(operation.operand))
        elif opcode is Opcode.STORE_LOCAL:
            expected = local_types.get(operation.operand)
            check_input(0, expected)
        elif opcode is Opcode.NOT:
            check_input(0, "bool")
            check_output("bool")
        elif opcode is Opcode.NEGATE:
            if known and input_types[0] not in scalar_numeric:
                report(f"NEGATE in block {block_id} requires a numeric input.")
            check_output(input_types[0] if input_types else None)
        elif opcode in (Opcode.AND, Opcode.OR):
            check_input(0, "bool")
            check_input(1, "bool")
            check_output("bool")
        elif opcode in _BINARY:
            left = input_types[0] if input_types else None
            right = input_types[1] if len(input_types) > 1 else None
            if opcode in (Opcode.EQUAL, Opcode.NOT_EQUAL):
                if left is not None and right is not None and left != right:
                    report(f"{opcode.value} in block {block_id} has mismatched input types.")
                check_output("bool")
            elif opcode in (Opcode.LESS, Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL):
                if known and (left not in scalar_numeric or right != left):
                    report(f"{opcode.value} in block {block_id} requires matching numeric inputs.")
                check_output("bool")
            elif opcode is Opcode.ADD and left == right == "string":
                check_output("string")
            else:
                if known and (left not in scalar_numeric or right != left):
                    report(f"{opcode.value} in block {block_id} requires matching numeric inputs.")
                check_output("float" if opcode is Opcode.DIVIDE and left in scalar_numeric else left)
                if opcode is Opcode.MODULO and known and left != "int":
                    report(f"MODULO in block {block_id} requires integer inputs.")
        elif opcode in array_element:
            expected_element = array_element[opcode]
            if known and any(item != expected_element for item in input_types):
                report(f"{opcode.value} in block {block_id} has an element type mismatch.")
            check_output(expected_element + "[]")
        elif opcode in (Opcode.ARRAY_GET, Opcode.ARRAY_SET, Opcode.ARRAY_PUSH, Opcode.ARRAY_POP):
            array_type = input_types[0] if input_types else None
            if array_type is not None and not array_type.endswith("[]"):
                report(f"{opcode.value} in block {block_id} requires an array operand.")
            element_type = array_type[:-2] if array_type and array_type.endswith("[]") else None
            if opcode in (Opcode.ARRAY_GET, Opcode.ARRAY_SET):
                check_input(1, "int")
            if opcode is Opcode.ARRAY_GET:
                check_output(element_type)
            elif opcode is Opcode.ARRAY_SET:
                check_input(2, element_type)
            elif opcode is Opcode.ARRAY_PUSH:
                check_input(1, element_type)
            else:
                check_output(element_type)
        elif opcode is Opcode.LENGTH:
            value_type = input_types[0] if input_types else None
            if value_type is not None and value_type != "string" and not value_type.endswith("[]"):
                report(f"LENGTH in block {block_id} requires a string or array.")
            check_output("int")
        elif opcode is Opcode.CALL:
            target = functions.get(operation.operand)
            if target is not None:
                for index, expected in enumerate(target.parameter_types):
                    check_input(index, expected)
                check_output(target.return_type if target.return_type != "void" else None)
            elif operation.operand in BUILTIN_ARITIES:
                # Built-in signatures are checked by the semantic analyzer;
                # runtime validation remains mandatory for serialized bytecode.
                pass
        elif opcode is Opcode.STRUCT_NEW:
            type_name = operation.operand.split("|", 1)[0] if isinstance(operation.operand, str) else None
            check_output(type_name)
        elif opcode is Opcode.ENUM_NEW:
            type_name = operation.operand.split("|", 1)[0] if isinstance(operation.operand, str) else None
            check_output(type_name)
        elif opcode is Opcode.ENUM_NEW_PAYLOAD:
            parts = operation.operand.split("|", 2) if isinstance(operation.operand, str) else ()
            check_output(parts[0] if parts else None)
            payload_types = parts[2].split(",") if len(parts) == 3 and parts[2] else []
            if tuple(payload_types) != tuple(input_types):
                report(f"ENUM_NEW_PAYLOAD in block {block_id} has payload type mismatch.")
        elif opcode is Opcode.ENUM_IS:
            enum_name = operation.operand.split("|", 1)[0] if isinstance(operation.operand, str) else None
            check_input(0, enum_name)
            check_output("bool")
        elif opcode is Opcode.ENUM_GET:
            parts = operation.operand.split("|", 3) if isinstance(operation.operand, str) else ()
            if len(parts) == 4:
                check_input(0, parts[0])
                check_output(parts[3])
        elif opcode in (Opcode.FIELD_GET, Opcode.FIELD_SET):
            if input_types and input_types[0] is not None and input_types[0] in {
                "int", "float", "bool", "string"
            }:
                report(f"{opcode.value} in block {block_id} requires a struct value.")

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
            if target is not None:
                return target.arity, 1 if target.return_type != "void" else 0
            if operation.operand in BUILTIN_ARITIES:
                return BUILTIN_ARITIES[operation.operand], 1
            report(f"CALL references unknown function {operation.operand!r}.")
            return None, None
        if opcode in (Opcode.STRUCT_NEW, Opcode.ENUM_NEW):
            if not isinstance(operation.operand, str) or not operation.operand:
                report(f"{opcode.value} requires a string type operand.")
            return 0, 1
        if opcode is Opcode.ENUM_NEW_PAYLOAD:
            if not isinstance(operation.operand, str) or operation.operand.count("|") != 2:
                report("ENUM_NEW_PAYLOAD requires Enum|Variant|payload-types.")
                return None, 1
            payload_text = operation.operand.split("|", 2)[2]
            return (len(payload_text.split(",")) if payload_text else 0), 1
        if opcode in (Opcode.ENUM_IS, Opcode.ENUM_GET):
            if not isinstance(operation.operand, str) or not operation.operand:
                report(f"{opcode.value} requires an enum pattern operand.")
            return 1, 1
        if opcode is Opcode.FIELD_GET:
            if not isinstance(operation.operand, str) or not operation.operand:
                report("FIELD_GET requires a field name.")
            return 1, 1
        if opcode is Opcode.FIELD_SET:
            if not isinstance(operation.operand, str) or not operation.operand:
                report("FIELD_SET requires a field name.")
            return 2, 0
        report(f"unsupported IR operation {opcode!r}.")
        return None, None
