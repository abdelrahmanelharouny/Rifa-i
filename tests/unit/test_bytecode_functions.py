from rifai.bytecode import (
    BytecodeFunction,
    BytecodeModule,
    BytecodeVerifier,
    CodeChunk,
    Instruction,
    Opcode,
)


def test_verifier_accepts_valid_function_call_module():
    function = BytecodeFunction(
        name="identity",
        chunk=CodeChunk(
            name="identity",
            instructions=(
                Instruction(Opcode.LOAD_LOCAL, 0),
                Instruction(Opcode.RETURN),
            ),
            local_count=1,
            arity=1,
        ),
        parameter_types=("int",),
        return_type="int",
    )
    module = BytecodeModule(
        constants=(42,),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.CALL, "identity"),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
        functions=(function,),
    )
    assert BytecodeVerifier().verify(module).is_valid


def test_verifier_rejects_unknown_call_target():
    module = BytecodeModule(
        constants=(),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CALL, "missing"),
                Instruction(Opcode.HALT),
            ),
        ),
    )
    result = BytecodeVerifier().verify(module)
    assert any("does not exist" in item.message for item in result.diagnostics)


def test_verifier_rejects_function_return_stack_imbalance():
    function = BytecodeFunction(
        name="bad",
        chunk=CodeChunk(
            name="bad",
            instructions=(
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.CONSTANT, 1),
                Instruction(Opcode.RETURN),
            ),
            local_count=0,
            arity=0,
        ),
        parameter_types=(),
        return_type="int",
    )
    module = BytecodeModule(
        constants=(1, 2),
        main=CodeChunk(
            name="<main>",
            instructions=(Instruction(Opcode.HALT),),
        ),
        functions=(function,),
    )
    result = BytecodeVerifier().verify(module)
    assert any("requires stack depth 1" in item.message for item in result.diagnostics)


def test_verifier_rejects_duplicate_function_names():
    first = BytecodeFunction(
        "same",
        CodeChunk("same", (Instruction(Opcode.RETURN),)),
        (),
        "void",
    )
    second = BytecodeFunction(
        "same",
        CodeChunk("same", (Instruction(Opcode.RETURN),)),
        (),
        "void",
    )
    module = BytecodeModule(
        constants=(),
        main=CodeChunk("<main>", (Instruction(Opcode.HALT),)),
        functions=(first, second),
    )
    result = BytecodeVerifier().verify(module)
    assert any("Duplicate function" in item.message for item in result.diagnostics)
