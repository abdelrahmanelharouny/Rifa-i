"""Lower explicit-value IR back to verified, versioned Rifa'i bytecode."""

from __future__ import annotations

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode
from rifai.bytecode.module import BytecodeModule, NOMINAL_TYPES_FORMAT_VERSION
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.ir.model import IRBranch, IRFunction, IRHalt, IRJump, IRModule, IROperation, IRReturn
from rifai.ir.verifier import IRVerifier


class IRToBytecode:
    """Reconstruct the stack-machine target from verified IR blocks."""

    def lower(self, module: IRModule) -> BytecodeModule:
        if not isinstance(module, IRModule):
            raise TypeError("module must be an IRModule.")
        ir_validation = IRVerifier().verify(module)
        if not ir_validation.is_valid:
            raise ValueError(
                "Cannot lower invalid IR: " + "; ".join(ir_validation.diagnostics[:3])
            )

        materialize = (
            module.requires_materialized_values
            or module.format_version >= NOMINAL_TYPES_FORMAT_VERSION
        )
        main = self._lower_function_selected(module.main, materialize)
        functions = tuple(
            BytecodeFunction(
                name=function.name,
                chunk=self._lower_function_selected(function, materialize),
                parameter_types=function.parameter_types,
                return_type=function.return_type,
            )
            for function in module.functions
        )
        bytecode = BytecodeModule(
            constants=module.constants,
            main=main,
            source_name=module.source_name,
            format_version=module.format_version,
            functions=functions,
            debug_info=module.debug_info,
        )
        validation = BytecodeVerifier().verify(bytecode)
        if not validation.is_valid:
            messages = "; ".join(item.message for item in validation.diagnostics[:3])
            raise RuntimeError(f"IR lowering produced invalid bytecode: {messages}")
        return bytecode

    @classmethod
    def _lower_function_selected(
        cls,
        function: IRFunction,
        module_requires_materialization: bool,
    ) -> CodeChunk:
        if (
            module_requires_materialization
            and cls._requires_materialized_values(function)
        ):
            return cls._lower_materialized(function)
        return cls._lower_function(function)

    @staticmethod
    def _requires_materialized_values(function: IRFunction) -> bool:
        definitions: dict[int, int] = {}
        uses: dict[int, list[int]] = {}
        for block in function.blocks:
            for parameter in block.parameters:
                definitions[parameter.value_id] = block.block_id
            for operation in block.operations:
                for output in operation.outputs:
                    definitions[output.value_id] = block.block_id
                for value_id in operation.inputs:
                    uses.setdefault(value_id, []).append(block.block_id)
            term = block.terminator
            if isinstance(term, IRJump):
                values = term.arguments
            elif isinstance(term, IRBranch):
                values = (
                    term.condition,
                    *term.false_arguments,
                    *term.true_arguments,
                )
            elif isinstance(term, IRReturn) and term.value is not None:
                values = (term.value,)
            else:
                values = ()
            for value_id in values:
                uses.setdefault(value_id, []).append(block.block_id)

        for value_id, definition_block in definitions.items():
            locations = uses.get(value_id, [])
            if len(locations) != 1:
                return True
            if locations[0] != definition_block:
                return True
        return False

    @classmethod
    def _lower_function_auto(cls, function: IRFunction) -> CodeChunk:
        if cls._requires_materialized_values(function):
            return cls._lower_materialized(function)
        return cls._lower_function(function)

    @staticmethod
    def _lower_materialized(function: IRFunction) -> CodeChunk:
        """Lower arbitrary SSA uses through private local slots.

        Every virtual definition is materialized once. Operations reload their
        operands explicitly, and CFG edges copy block arguments through scratch
        slots so parallel phi assignments cannot overwrite one another.
        """
        blocks = tuple(sorted(function.blocks, key=lambda item: (
            item.source_start,
            item.block_id,
        )))
        if not blocks or blocks[0].block_id != 0:
            raise ValueError(f"IR function '{function.name}' has no entry block.")

        block_map = {block.block_id: block for block in blocks}
        value_ids = sorted({
            value.value_id
            for block in blocks
            for value in (
                *block.parameters,
                *(
                    output
                    for operation in block.operations
                    for output in operation.outputs
                ),
            )
        })
        value_slots = {
            value_id: function.local_count + index
            for index, value_id in enumerate(value_ids)
        }
        scratch_count = max(
            (len(block.parameters) for block in blocks),
            default=0,
        )
        scratch_start = function.local_count + len(value_slots)
        final_local_count = scratch_start + scratch_count
        if final_local_count > 100_000:
            raise ValueError(
                f"Materialized IR values exceed the local-frame limit in '{function.name}'."
            )

        def slot_for(value_id: int) -> int:
            try:
                return value_slots[value_id]
            except KeyError as exc:
                raise ValueError(
                    f"IR function '{function.name}' references undefined value %{value_id}."
                ) from exc

        output: list[Instruction] = []
        block_offsets: dict[int, int] = {}
        jump_patches: list[tuple[int, int]] = []
        false_edge_stubs: list[tuple[int, int, tuple[int, ...], object]] = []
        halt_patches: list[int] = []

        def emit(opcode: Opcode, operand=None, location=None) -> int:
            output.append(Instruction(opcode, operand, location))
            return len(output) - 1

        def emit_edge_copies(arguments: tuple[int, ...], target_id: int, location) -> None:
            target = block_map.get(target_id)
            if target is None:
                raise ValueError(
                    f"IR function '{function.name}' jumps to missing block {target_id}."
                )
            if len(arguments) != len(target.parameters):
                raise ValueError(
                    f"IR edge to block {target_id} has an invalid argument count."
                )
            if not arguments:
                return
            # Stage all sources first, then write destinations: this is a
            # parallel copy even when loop-carried values form a swap/cycle.
            for index, value_id in enumerate(arguments):
                emit(Opcode.LOAD_LOCAL, slot_for(value_id), location)
                emit(Opcode.STORE_LOCAL, scratch_start + index, location)
            for index, parameter in enumerate(target.parameters):
                emit(Opcode.LOAD_LOCAL, scratch_start + index, location)
                emit(Opcode.STORE_LOCAL, slot_for(parameter.value_id), location)

        for block in blocks:
            block_offsets[block.block_id] = len(output)
            for operation in block.operations:
                if not isinstance(operation, IROperation):
                    raise ValueError(
                        f"IR block {block.block_id} contains an invalid operation."
                    )
                if operation.opcode is Opcode.DUP:
                    if len(operation.inputs) != 1 or len(operation.outputs) != 1:
                        raise ValueError("DUP must have one input and one output in IR.")
                    emit(
                        Opcode.LOAD_LOCAL,
                        slot_for(operation.inputs[0]),
                        operation.location,
                    )
                    emit(
                        Opcode.STORE_LOCAL,
                        slot_for(operation.outputs[0].value_id),
                        operation.location,
                    )
                    continue

                for value_id in operation.inputs:
                    emit(Opcode.LOAD_LOCAL, slot_for(value_id), operation.location)
                emit(operation.opcode, operation.operand, operation.location)
                if operation.outputs:
                    if len(operation.outputs) != 1:
                        raise ValueError(
                            f"Unsupported multi-result operation {operation.opcode.value}."
                        )
                    emit(
                        Opcode.STORE_LOCAL,
                        slot_for(operation.outputs[0].value_id),
                        operation.location,
                    )

            term = block.terminator
            if isinstance(term, IRJump):
                emit_edge_copies(term.arguments, term.target, term.location)
                patch = emit(Opcode.JUMP, -1, term.location)
                jump_patches.append((patch, term.target))
            elif isinstance(term, IRBranch):
                emit(Opcode.LOAD_LOCAL, slot_for(term.condition), term.location)
                false_patch = emit(Opcode.JUMP_IF_FALSE, -1, term.location)
                emit_edge_copies(term.true_arguments, term.true_target, term.location)
                true_patch = emit(Opcode.JUMP, -1, term.location)
                jump_patches.append((true_patch, term.true_target))
                false_edge_stubs.append((
                    false_patch,
                    term.false_target,
                    term.false_arguments,
                    term.location,
                ))
            elif isinstance(term, IRReturn):
                if term.value is not None:
                    emit(Opcode.LOAD_LOCAL, slot_for(term.value), term.location)
                emit(Opcode.RETURN, location=term.location)
            elif isinstance(term, IRHalt):
                # Main HALT must be the final bytecode instruction. A materialized
                # branch path appends edge stubs after normal blocks, so route the
                # halt block to one final sentinel emitted after all stubs.
                halt_patches.append(emit(Opcode.JUMP, -1, term.location))
            else:
                raise ValueError(
                    f"Unsupported terminator in IR function '{function.name}'."
                )

        for false_patch, target_id, arguments, location in false_edge_stubs:
            stub_offset = len(output)
            original = output[false_patch]
            output[false_patch] = Instruction(
                Opcode.JUMP_IF_FALSE,
                stub_offset,
                original.location,
            )
            emit_edge_copies(arguments, target_id, location)
            patch = emit(Opcode.JUMP, -1, location)
            jump_patches.append((patch, target_id))

        if halt_patches:
            halt_offset = len(output)
            emit(Opcode.HALT)
            for instruction_index in halt_patches:
                original = output[instruction_index]
                output[instruction_index] = Instruction(
                    Opcode.JUMP,
                    halt_offset,
                    original.location,
                )

        for instruction_index, target_id in jump_patches:
            target_offset = block_offsets.get(target_id)
            if target_offset is None:
                raise ValueError(
                    f"IR function '{function.name}' jumps to missing block {target_id}."
                )
            original = output[instruction_index]
            output[instruction_index] = Instruction(
                Opcode.JUMP,
                target_offset,
                original.location,
            )

        return CodeChunk(
            name=function.name,
            instructions=tuple(output),
            local_count=final_local_count,
            arity=function.arity,
        )

    @staticmethod
    def _lower_function(function: IRFunction) -> CodeChunk:
        blocks = tuple(sorted(function.blocks, key=lambda item: item.source_start))
        if not blocks or blocks[0].block_id != 0:
            raise ValueError(f"IR function '{function.name}' has no entry block.")

        block_sizes: dict[int, int] = {}
        for index, block in enumerate(blocks):
            next_block = blocks[index + 1] if index + 1 < len(blocks) else None
            term = block.terminator
            terminator_size = 1
            if isinstance(term, IRJump) and term.fallthrough and (
                next_block is not None and next_block.block_id == term.target
            ):
                terminator_size = 0
            elif isinstance(term, IRBranch) and (
                next_block is not None and next_block.block_id == term.true_target
            ):
                terminator_size = 1
            elif isinstance(term, IRBranch):
                terminator_size = 2
            block_sizes[block.block_id] = len(block.operations) + terminator_size

        block_offsets: dict[int, int] = {}
        offset = 0
        for block in blocks:
            block_offsets[block.block_id] = offset
            offset += block_sizes[block.block_id]

        output: list[Instruction] = []
        for index, block in enumerate(blocks):
            next_block = blocks[index + 1] if index + 1 < len(blocks) else None
            for operation in block.operations:
                output.append(
                    Instruction(operation.opcode, operation.operand, operation.location)
                )

            term = block.terminator
            if isinstance(term, IRJump):
                if term.fallthrough and next_block is not None and next_block.block_id == term.target:
                    continue
                output.append(
                    Instruction(Opcode.JUMP, block_offsets[term.target], term.location)
                )
            elif isinstance(term, IRBranch):
                output.append(
                    Instruction(
                        Opcode.JUMP_IF_FALSE,
                        block_offsets[term.false_target],
                        term.location,
                    )
                )
                if next_block is None or next_block.block_id != term.true_target:
                    output.append(
                        Instruction(Opcode.JUMP, block_offsets[term.true_target], term.location)
                    )
            elif isinstance(term, IRReturn):
                output.append(Instruction(Opcode.RETURN, location=term.location))
            elif isinstance(term, IRHalt):
                output.append(Instruction(Opcode.HALT, location=term.location))
            else:
                raise ValueError(f"Unsupported terminator in IR function '{function.name}'.")

        return CodeChunk(
            name=function.name,
            instructions=tuple(output),
            local_count=function.local_count,
            arity=function.arity,
        )
