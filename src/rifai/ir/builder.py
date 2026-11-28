"""Lower verified stack bytecode into explicit-value, block-parameter IR."""

from __future__ import annotations

from collections import deque

from rifai.bytecode.cfg import ControlFlowGraph, build_control_flow_graph
from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode, stack_delta
from rifai.bytecode.module import BytecodeModule
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.stdlib import BUILTIN_ARITIES
from rifai.ir.model import (
    IRBlock,
    IRBranch,
    IRFunction,
    IRHalt,
    IRJump,
    IRLocal,
    IROperation,
    IRModule,
    IRReturn,
    IRValue,
)


_ARRAY_TYPES = {
    Opcode.ARRAY_NEW_INT: "int[]",
    Opcode.ARRAY_NEW_FLOAT: "float[]",
    Opcode.ARRAY_NEW_BOOL: "bool[]",
    Opcode.ARRAY_NEW_STRING: "string[]",
}
_COMPARISONS = frozenset({
    Opcode.EQUAL, Opcode.NOT_EQUAL, Opcode.LESS, Opcode.LESS_EQUAL,
    Opcode.GREATER, Opcode.GREATER_EQUAL, Opcode.AND, Opcode.OR,
})
_BINARY = frozenset({
    Opcode.ADD, Opcode.SUBTRACT, Opcode.MULTIPLY, Opcode.DIVIDE,
    Opcode.MODULO, Opcode.EQUAL, Opcode.NOT_EQUAL, Opcode.LESS,
    Opcode.LESS_EQUAL, Opcode.GREATER, Opcode.GREATER_EQUAL,
    Opcode.AND, Opcode.OR,
})
_UNARY = frozenset({Opcode.NEGATE, Opcode.NOT})


def _constant_type(value: object) -> str | None:
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "float"
    if type(value) is str:
        return "string"
    return None


def _operation_type(
    instruction: Instruction,
    inputs: tuple[IRValue, ...],
    constants: tuple[object, ...],
    functions: dict[str, BytecodeFunction],
    local_types: dict[int, str],
) -> str | None:
    opcode = instruction.opcode
    types = tuple(item.type_name for item in inputs)
    if opcode is Opcode.CONSTANT:
        return _constant_type(constants[instruction.operand])
    if opcode is Opcode.LOAD_LOCAL:
        return local_types.get(instruction.operand)
    if opcode is Opcode.LOAD_GLOBAL:
        return None
    if opcode is Opcode.NOT:
        return "bool"
    if opcode is Opcode.NEGATE:
        return types[0]
    if opcode in _COMPARISONS:
        return "bool"
    if opcode is Opcode.ADD and types == ("string", "string"):
        return "string"
    if opcode is Opcode.DIVIDE:
        return "float" if types[0] in ("int", "float") and types[0] == types[1] else None
    if opcode in _BINARY:
        return types[0] if types[0] == types[1] else None
    if opcode is Opcode.CALL:
        target = functions.get(instruction.operand)
        if target is not None:
            return target.return_type if target.returns_value else None
        builtin_result_types = {
            "sqrt": "float",
            "round": "int",
            "to_int": "int",
            "to_float": "float",
            "to_string": "string",
            "contains": "bool",
            "starts_with": "bool",
            "ends_with": "bool",
            "substring": "string",
            "read_text": "string",
            "write_text": "bool",
            "file_exists": "bool",
        }
        if instruction.operand in ("abs", "min", "max"):
            return types[0] if types and all(item == types[0] for item in types) else None
        return builtin_result_types.get(instruction.operand)
    if opcode is Opcode.STRUCT_NEW:
        return instruction.operand.split("|", 1)[0] if isinstance(instruction.operand, str) else None
    if opcode is Opcode.ENUM_NEW:
        return instruction.operand.split("|", 1)[0] if isinstance(instruction.operand, str) else None
    if opcode is Opcode.ENUM_NEW_PAYLOAD:
        return instruction.operand.split("|", 1)[0] if isinstance(instruction.operand, str) else None
    if opcode is Opcode.ENUM_IS:
        return "bool"
    if opcode is Opcode.ENUM_GET:
        return instruction.operand.split("|", 3)[3] if isinstance(instruction.operand, str) else None
    if opcode is Opcode.FIELD_GET:
        return None
    if opcode in _ARRAY_TYPES:
        return _ARRAY_TYPES[opcode]
    if opcode is Opcode.ARRAY_GET:
        return types[0][:-2] if types[0] and types[0].endswith("[]") else None
    if opcode is Opcode.LENGTH:
        return "int"
    if opcode is Opcode.ARRAY_POP:
        return types[0][:-2] if types[0] and types[0].endswith("[]") else None
    return None


def _stack_effect(
    instruction: Instruction,
    functions: dict[str, BytecodeFunction],
    return_type: str,
) -> tuple[int, int]:
    opcode = instruction.opcode
    if opcode is Opcode.CALL:
        target = functions.get(instruction.operand)
        if target is not None:
            return target.arity, 1 if target.returns_value else 0
        return BUILTIN_ARITIES[instruction.operand], 1
    if opcode in _ARRAY_TYPES:
        return instruction.operand, 1
    if opcode is Opcode.ENUM_NEW_PAYLOAD:
        payload_text = instruction.operand.split("|", 2)[2]
        return (len(payload_text.split(",")) if payload_text else 0), 1
    if opcode in (Opcode.ENUM_IS, Opcode.ENUM_GET):
        return 1, 1
    if opcode is Opcode.RETURN:
        return (1 if return_type != "void" else 0), 0
    if opcode is Opcode.HALT:
        return 0, 0
    if opcode is Opcode.DUP:
        return 1, 2
    required = {
        Opcode.POP: 1, Opcode.STORE_LOCAL: 1, Opcode.STORE_GLOBAL: 1,
        Opcode.PRINT: 1, Opcode.JUMP_IF_FALSE: 1, Opcode.NEGATE: 1,
        Opcode.NOT: 1, Opcode.LENGTH: 1, Opcode.ARRAY_POP: 1,
        Opcode.ARRAY_GET: 2, Opcode.ARRAY_SET: 3, Opcode.ARRAY_PUSH: 2,
        Opcode.FIELD_GET: 1, Opcode.FIELD_SET: 2,
    }.get(opcode)
    if required is None and opcode in _BINARY:
        required = 2
    if required is None:
        required = 0
    delta = stack_delta(opcode)
    return required, required + delta


class BytecodeToIR:
    """Lift verified bytecode into a typed, explicit-value IR module."""

    def build(self, module: BytecodeModule) -> IRModule:
        if not isinstance(module, BytecodeModule):
            raise TypeError("module must be a BytecodeModule.")
        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            messages = "; ".join(item.message for item in validation.diagnostics[:3])
            raise ValueError(f"Cannot build IR from invalid bytecode: {messages}")

        functions_by_name = {function.name: function for function in module.functions}
        local_metadata = module.debug_info.as_mapping() if module.debug_info else {}
        main = self._build_function(
            module.main,
            (),
            "void",
            functions_by_name,
            module.constants,
            local_metadata.get("<main>", {}),
        )
        functions = tuple(
            self._build_function(
                function.chunk,
                function.parameter_types,
                function.return_type,
                functions_by_name,
                module.constants,
                local_metadata.get(function.name, {}),
            )
            for function in module.functions
        )
        return IRModule(
            constants=module.constants,
            main=main,
            functions=functions,
            source_name=module.source_name,
            format_version=module.format_version,
            debug_info=module.debug_info,
        )

    def _build_function(
        self,
        chunk: CodeChunk,
        parameter_types: tuple[str, ...],
        return_type: str,
        functions: dict[str, BytecodeFunction],
        constants: tuple[object, ...],
        local_metadata: dict[int, tuple[str, str]],
    ) -> IRFunction:
        graph = build_control_flow_graph(chunk)
        heights = self._block_entry_heights(chunk, graph, functions, return_type)
        next_value_id = 0

        # Block parameters represent stack values entering from predecessor edges.
        parameters: dict[int, tuple[IRValue, ...]] = {}
        for block in graph.blocks:
            block_params = []
            for _ in range(heights.get(block.block_id, 0)):
                block_params.append(IRValue(next_value_id))
                next_value_id += 1
            parameters[block.block_id] = tuple(block_params)

        block_by_start = {block.start: block for block in graph.blocks}
        local_types = {slot: type_name for slot, (_, type_name) in local_metadata.items()}
        blocks: list[IRBlock] = []
        for block in graph.blocks:
            stack = list(parameters[block.block_id])
            operations: list[IROperation] = []
            terminator = None

            for index in range(block.start, block.end + 1):
                instruction = chunk.instructions[index]
                opcode = instruction.opcode

                if opcode is Opcode.JUMP:
                    terminator = IRJump(
                        instruction.operand,
                        tuple(item.value_id for item in stack),
                        False,
                        instruction.location,
                    )
                    break
                if opcode is Opcode.JUMP_IF_FALSE:
                    condition = self._take(stack, 1, instruction)[0]
                    true_block = block_by_start.get(block.end + 1)
                    if true_block is None:
                        raise ValueError(
                            f"Conditional block {block.block_id} has no fall-through block."
                        )
                    terminator = IRBranch(
                        condition.value_id,
                        instruction.operand,
                        true_block.block_id,
                        tuple(item.value_id for item in stack),
                        tuple(item.value_id for item in stack),
                        instruction.location,
                    )
                    break
                if opcode is Opcode.RETURN:
                    value = self._take(stack, 1, instruction)[0] if return_type != "void" else None
                    terminator = IRReturn(
                        None if value is None else value.value_id,
                        instruction.location,
                    )
                    break
                if opcode is Opcode.HALT:
                    terminator = IRHalt(instruction.location)
                    break

                required, produced = _stack_effect(instruction, functions, return_type)
                if opcode is Opcode.DUP:
                    inputs = (stack[-1],)
                    output_type = inputs[0].type_name
                    output = IRValue(next_value_id, output_type)
                    next_value_id += 1
                    outputs = (output,)
                    stack.append(output)
                else:
                    inputs = tuple(self._take(stack, required, instruction))
                    outputs: tuple[IRValue, ...]
                    if produced:
                        output_type = _operation_type(
                            instruction, inputs, constants, functions, local_types
                        )
                        outputs = (IRValue(next_value_id, output_type),)
                        next_value_id += 1
                        stack.extend(outputs)
                    else:
                        outputs = ()
                operations.append(
                    IROperation(
                        opcode=opcode,
                        outputs=outputs,
                        inputs=tuple(item.value_id for item in inputs),
                        operand=instruction.operand,
                        location=instruction.location,
                    )
                )

            if terminator is None:
                successors = block.successors
                if len(successors) != 1:
                    raise ValueError(
                        f"Block {block.block_id} in '{chunk.name}' has no explicit terminator."
                    )
                terminator = IRJump(
                    successors[0],
                    tuple(item.value_id for item in stack),
                    True,
                    chunk.instructions[block.end].location,
                )

            blocks.append(
                IRBlock(
                    block_id=block.block_id,
                    parameters=parameters[block.block_id],
                    operations=tuple(operations),
                    terminator=terminator,
                    source_start=block.start,
                    source_end=block.end,
                    reachable=block.block_id in graph.reachable_blocks,
                )
            )

        # Infer block-parameter types from identical incoming edge values.
        value_types = {
            value.value_id: value.type_name
            for ir_block in blocks
            for value in ir_block.parameters
        }
        value_types.update({
            output.value_id: output.type_name
            for ir_block in blocks
            for operation in ir_block.operations
            for output in operation.outputs
        })
        block_map = {ir_block.block_id: ir_block for ir_block in blocks}
        incoming_types: dict[tuple[int, int], list[str | None]] = {}
        for ir_block in blocks:
            term = ir_block.terminator
            if isinstance(term, IRJump):
                edges = ((term.target, term.arguments),)
            elif isinstance(term, IRBranch):
                edges = (
                    (term.false_target, term.false_arguments),
                    (term.true_target, term.true_arguments),
                )
            else:
                edges = ()
            if not ir_block.reachable:
                continue
            for target, arguments in edges:
                target_block = block_map.get(target)
                if target_block is None:
                    continue
                for position, value_id in enumerate(arguments):
                    incoming_types.setdefault((target, position), []).append(
                        value_types.get(value_id)
                    )
        typed_blocks = []
        for ir_block in blocks:
            typed_parameters = []
            for position, parameter in enumerate(ir_block.parameters):
                candidates = incoming_types.get((ir_block.block_id, position), [])
                known = {item for item in candidates if item is not None}
                inferred = next(iter(known)) if candidates and len(known) == 1 and all(
                    item is not None for item in candidates
                ) else parameter.type_name
                typed_parameters.append(IRValue(parameter.value_id, inferred))
            typed_blocks.append(
                IRBlock(
                    block_id=ir_block.block_id,
                    parameters=tuple(typed_parameters),
                    operations=ir_block.operations,
                    terminator=ir_block.terminator,
                    source_start=ir_block.source_start,
                    source_end=ir_block.source_end,
                    reachable=ir_block.reachable,
                )
            )
        blocks = typed_blocks

        locals_ = tuple(
            IRLocal(slot, name, type_name)
            for slot, (name, type_name) in sorted(local_metadata.items())
        )
        return IRFunction(
            name=chunk.name,
            blocks=tuple(blocks),
            local_count=chunk.local_count,
            arity=chunk.arity,
            parameter_types=parameter_types,
            return_type=return_type,
            local_symbols=locals_,
        )

    @staticmethod
    def _take(stack: list[IRValue], count: int, instruction: Instruction) -> list[IRValue]:
        if count < 0 or len(stack) < count:
            raise ValueError(
                f"IR stack underflow while lifting {instruction.opcode.value}."
            )
        if count == 0:
            return []
        values = stack[-count:]
        del stack[-count:]
        return values

    @staticmethod
    def _block_entry_heights(
        chunk: CodeChunk,
        graph: ControlFlowGraph,
        functions: dict[str, BytecodeFunction],
        return_type: str,
    ) -> dict[int, int]:
        if graph.entry_block is None:
            return {}
        by_id = {block.block_id: block for block in graph.blocks}
        heights: dict[int, int] = {}

        def minimum_entry_height(block) -> int:
            # A disconnected function epilogue can contain an unreachable
            # value-return instruction; reserve one abstract return slot for
            # non-void functions when seeding an unreachable island.
            height = 1 if return_type != "void" else 0
            initial = height
            for index in range(block.start, block.end + 1):
                instruction = chunk.instructions[index]
                required, produced = _stack_effect(instruction, functions, return_type)
                if height < required:
                    deficit = required - height
                    initial += deficit
                    height += deficit
                if instruction.opcode is Opcode.RETURN:
                    height = 0
                elif instruction.opcode is Opcode.JUMP_IF_FALSE:
                    height -= required
                elif instruction.opcode not in (Opcode.JUMP, Opcode.HALT):
                    height = height - required + produced
            return initial

        def propagate(seed: int) -> None:
            if seed in heights:
                return
            heights[seed] = minimum_entry_height(by_id[seed])
            queue = deque([seed])
            while queue:
                block_id = queue.popleft()
                block = by_id[block_id]
                height = heights[block_id]
                for index in range(block.start, block.end + 1):
                    instruction = chunk.instructions[index]
                    required, produced = _stack_effect(instruction, functions, return_type)
                    if instruction.opcode is Opcode.RETURN:
                        height = 0
                    elif instruction.opcode is Opcode.JUMP_IF_FALSE:
                        height = height - required
                    elif instruction.opcode not in (Opcode.JUMP, Opcode.HALT):
                        height = height - required + produced
                for successor in block.successors:
                    if successor not in heights:
                        heights[successor] = height
                        queue.append(successor)
                    elif graph.block_count and heights[successor] != height:
                        if block_id in graph.reachable_blocks and successor in graph.reachable_blocks:
                            raise ValueError(
                                f"IR stack-height mismatch at block {successor} in '{chunk.name}'."
                            )

        propagate(graph.entry_block)
        # Unreachable islands are still represented losslessly. Seed each
        # disconnected component with an empty operand stack.
        for block in graph.blocks:
            if block.block_id not in heights:
                propagate(block.block_id)
        return heights
