"""Lower explicit-value IR back to verified, versioned Rifa'i bytecode."""

from __future__ import annotations

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode
from rifai.bytecode.module import BytecodeModule
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.ir.model import IRBranch, IRFunction, IRHalt, IRJump, IRModule, IRReturn
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

        main = self._lower_function(module.main)
        functions = tuple(
            BytecodeFunction(
                name=function.name,
                chunk=self._lower_function(function),
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
