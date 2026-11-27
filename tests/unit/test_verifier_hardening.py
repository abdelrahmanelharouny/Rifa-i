import pytest

from rifai.bytecode import BytecodeModule, CodeChunk, Instruction, Opcode, SourceLocation
from rifai.bytecode.verifier import BytecodeVerifier


def module_with(instruction):
    return BytecodeModule(
        constants=(),
        main=CodeChunk("<main>", (instruction,)),
    )


def test_rejects_non_source_location_metadata_without_crashing():
    result = BytecodeVerifier().verify(
        module_with(Instruction(Opcode.HALT, location="not-a-source-location"))
    )
    assert not result.is_valid
    assert any("invalid source location" in item.message for item in result.diagnostics)


@pytest.mark.parametrize(
    "location",
    [
        SourceLocation(0, 1, 0, 1),
        SourceLocation(1, 0, 0, 1),
        SourceLocation(1, 1, -1, 1),
        SourceLocation(1, 1, 3, 2),
        SourceLocation(True, 1, 0, 1),
    ],
)
def test_rejects_invalid_source_coordinates(location):
    result = BytecodeVerifier().verify(
        module_with(Instruction(Opcode.HALT, location=location))
    )
    assert not result.is_valid
    assert any("invalid source coordinates" in item.message for item in result.diagnostics)


def test_invalid_function_parameter_metadata_is_reported_without_crashing():
    from rifai.bytecode import BytecodeFunction

    function = BytecodeFunction(
        name="bad",
        chunk=CodeChunk(
            "bad",
            (Instruction(Opcode.RETURN),),
            arity=0,
        ),
        parameter_types=(),
        return_type="void",
    )
    object.__setattr__(function, "parameter_types", None)
    module = BytecodeModule(
        constants=(),
        main=CodeChunk("<main>", (Instruction(Opcode.HALT),)),
        functions=(function,),
    )

    result = BytecodeVerifier().verify(module)
    assert not result.is_valid
    assert any("invalid parameter types" in item.message for item in result.diagnostics)


def test_verifier_rejects_unbounded_local_frame_size():
    from rifai.bytecode.verifier import MAX_LOCAL_COUNT

    module = BytecodeModule(
        constants=(),
        main=CodeChunk(
            "<main>",
            (Instruction(Opcode.HALT),),
            local_count=MAX_LOCAL_COUNT + 1,
        ),
    )
    result = BytecodeVerifier().verify(module)
    assert not result.is_valid
    assert any("local_count exceeds the limit" in item.message for item in result.diagnostics)


def test_call_to_invalid_function_signature_is_rejected_without_crashing():
    from rifai.bytecode import BytecodeFunction

    function = BytecodeFunction(
        name="broken",
        chunk=CodeChunk(
            "broken",
            (Instruction(Opcode.RETURN),),
            arity=0,
        ),
        parameter_types=(),
        return_type="void",
    )
    object.__setattr__(function, "parameter_types", None)
    module = BytecodeModule(
        constants=(),
        main=CodeChunk(
            "<main>",
            (
                Instruction(Opcode.CALL, "broken"),
                Instruction(Opcode.HALT),
            ),
        ),
        functions=(function,),
    )

    result = BytecodeVerifier().verify(module)
    assert not result.is_valid
    messages = [item.message for item in result.diagnostics]
    assert any("invalid parameter types" in message for message in messages)
    assert any("Call target 'broken' does not exist" in message for message in messages)
