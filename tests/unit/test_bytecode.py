from rifai.bytecode import (
    BytecodeModule,
    BytecodeVerifier,
    CodeChunk,
    Instruction,
    Opcode,
    SourceLocation,
)


def module_with(*instructions, constants=(), local_count=0):
    return BytecodeModule(
        constants=tuple(constants),
        main=CodeChunk(
            name="<main>",
            instructions=tuple(instructions),
            local_count=local_count,
        ),
        source_name="test.rif",
    )


def test_valid_constant_print_halt_module():
    module = module_with(
        Instruction(Opcode.CONSTANT, 0),
        Instruction(Opcode.PRINT),
        Instruction(Opcode.HALT),
        constants=(42,),
    )
    result = BytecodeVerifier().verify(module)
    assert result.is_valid
    assert result.diagnostics == ()


def test_rejects_missing_halt():
    module = module_with(Instruction(Opcode.CONSTANT, 0), constants=(1,))
    result = BytecodeVerifier().verify(module)
    assert any("end with HALT" in item.message for item in result.diagnostics)


def test_rejects_stack_underflow():
    module = module_with(Instruction(Opcode.ADD), Instruction(Opcode.HALT))
    result = BytecodeVerifier().verify(module)
    assert any("Stack underflow" in item.message for item in result.diagnostics)


def test_rejects_invalid_constant_index():
    module = module_with(
        Instruction(Opcode.CONSTANT, 2),
        Instruction(Opcode.POP),
        Instruction(Opcode.HALT),
    )
    result = BytecodeVerifier().verify(module)
    assert any("out of range" in item.message for item in result.diagnostics)


def test_rejects_invalid_local_slot():
    module = module_with(
        Instruction(Opcode.LOAD_LOCAL, 0),
        Instruction(Opcode.POP),
        Instruction(Opcode.HALT),
        local_count=0,
    )
    result = BytecodeVerifier().verify(module)
    assert any("Local slot" in item.message for item in result.diagnostics)


def test_rejects_invalid_jump_target():
    module = module_with(
        Instruction(Opcode.JUMP, 9),
        Instruction(Opcode.HALT),
    )
    result = BytecodeVerifier().verify(module)
    assert any("Jump target" in item.message for item in result.diagnostics)


def test_checks_stack_depth_at_control_flow_merge():
    module = module_with(
        Instruction(Opcode.CONSTANT, 0),
        Instruction(Opcode.JUMP_IF_FALSE, 4),
        Instruction(Opcode.CONSTANT, 1),
        Instruction(Opcode.JUMP, 5),
        Instruction(Opcode.JUMP, 5),
        Instruction(Opcode.HALT),
        constants=(True, 7),
    )
    result = BytecodeVerifier().verify(module)
    assert any("Inconsistent stack depth" in item.message for item in result.diagnostics)


def test_accepts_balanced_conditional_control_flow():
    module = module_with(
        Instruction(Opcode.CONSTANT, 0),
        Instruction(Opcode.JUMP_IF_FALSE, 4),
        Instruction(Opcode.CONSTANT, 1),
        Instruction(Opcode.PRINT),
        Instruction(Opcode.HALT),
        constants=(True, 7),
    )
    result = BytecodeVerifier().verify(module)
    assert result.is_valid


def test_reports_source_location_for_verification_error():
    location = SourceLocation(8, 3, 40, 41)
    module = module_with(
        Instruction(Opcode.ADD, location=location),
        Instruction(Opcode.HALT),
    )
    result = BytecodeVerifier().verify(module)
    assert result.diagnostics[0].line == 8
    assert result.diagnostics[0].column == 3
