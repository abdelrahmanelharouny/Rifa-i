import pytest

from rifai.bytecode import BytecodeModule, CodeChunk, Instruction, Opcode
from rifai.bytecode.serializer import BytecodeFormatError, BytecodeSerializer


def test_atomic_write_replaces_existing_file_without_leaving_temporary_files(tmp_path):
    target = tmp_path / "program.rbc"
    target.write_bytes(b"old content")
    module = BytecodeModule(
        constants=(42,),
        main=CodeChunk(
            "<main>",
            (
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
    )

    BytecodeSerializer.write(module, target)

    assert BytecodeSerializer.read(target) == module
    assert not list(tmp_path.glob(".program.rbc.*.tmp"))


def test_read_rejects_oversized_bytecode_file_before_parsing(tmp_path):
    from rifai.bytecode.serializer import MAX_BYTECODE_SIZE

    target = tmp_path / "oversized.rbc"
    with target.open("wb") as stream:
        stream.truncate(MAX_BYTECODE_SIZE + 1)
    with pytest.raises(BytecodeFormatError, match="maximum file size"):
        BytecodeSerializer.read(target)
