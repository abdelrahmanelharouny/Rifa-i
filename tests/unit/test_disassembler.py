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
    assert "Rifa'i Bytecode v7" in listing
    assert "hello.rif" in listing
    assert "INTEGER" not in listing
    assert "CONSTANT" in listing
    assert "123" in listing
    assert "source 2:4" in listing
    assert "HALT" in listing


def test_disassembler_includes_function_signatures_and_chunks():
    from rifai.bytecode import BytecodeFunction

    function = BytecodeFunction(
        "double",
        CodeChunk(
            "double",
            (Instruction(Opcode.LOAD_LOCAL, 0), Instruction(Opcode.RETURN)),
            local_count=1,
            arity=1,
        ),
        ("int",),
        "int",
    )
    module = BytecodeModule(
        constants=(),
        main=CodeChunk("<main>", (Instruction(Opcode.HALT),)),
        functions=(function,),
    )
    listing = disassemble(module)
    assert "Function: double(int) -> int" in listing
    assert "LOAD_LOCAL" in listing
    assert "RETURN" in listing
