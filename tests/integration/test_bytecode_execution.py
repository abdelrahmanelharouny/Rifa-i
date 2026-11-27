from rifai.bytecode import (
    BytecodeModule,
    BytecodeSerializer,
    CodeChunk,
    Instruction,
    Opcode,
)
from rifai.vm import VirtualMachine


def test_serialized_bytecode_executes_after_reload(tmp_path):
    module = BytecodeModule(
        constants=(20, 22),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.CONSTANT, 1),
                Instruction(Opcode.ADD),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
        source_name="integration.rif",
    )
    output_path = tmp_path / "program.rbc"
    BytecodeSerializer.write(module, output_path)

    reloaded = BytecodeSerializer.read(output_path)
    result = VirtualMachine().execute(reloaded)

    assert result.output == ("42",)
    assert result.instructions_executed == 5
