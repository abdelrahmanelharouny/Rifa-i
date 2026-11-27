from rifai.bytecode import BytecodeModule, CodeChunk, Instruction, Opcode, SourceLocation, disassemble


def test_disassembler_shows_constants_opcodes_and_source_locations():
    module = BytecodeModule(
        constants=(123,),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CONSTANT, 0, SourceLocation(2, 4, 10, 13)),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
        source_name="hello.rif",
    )
    listing = disassemble(module)
    assert "Rifa'i Bytecode v1" in listing
    assert "hello.rif" in listing
    assert "INTEGER" not in listing
    assert "CONSTANT" in listing
    assert "123" in listing
    assert "source 2:4" in listing
    assert "HALT" in listing


def test_disassembler_does_not_crash_on_invalid_constant_reference():
    module = BytecodeModule(
        constants=(),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CONSTANT, 99),
                Instruction(Opcode.HALT),
            ),
        ),
    )
    assert "invalid constant index" in disassemble(module)
