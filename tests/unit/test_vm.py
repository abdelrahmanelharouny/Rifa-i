import pytest

from rifai.bytecode import BytecodeModule, CodeChunk, Instruction, Opcode
from rifai.vm import VMRuntimeError, VirtualMachine


def make_module(instructions, constants=(), local_count=0):
    return BytecodeModule(
        constants=tuple(constants),
        main=CodeChunk(
            name="<main>",
            instructions=tuple(instructions),
            local_count=local_count,
        ),
        source_name="vm-test.rif",
    )


def test_executes_integer_arithmetic_and_print():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.ADD),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=(10, 20),
    )
    result = VirtualMachine().execute(module)
    assert result.output == ("30",)
    assert result.instructions_executed == 5
    assert result.final_stack == ()


def test_executes_string_concatenation():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.ADD),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=("Rifa", "'i"),
    )
    assert VirtualMachine().execute(module).output == ("Rifa'i",)


def test_executes_float_division():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.DIVIDE),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=(10, 2),
    )
    assert VirtualMachine().execute(module).output == ("5.0",)


def test_executes_local_and_global_storage():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.STORE_LOCAL, 0),
            Instruction(Opcode.LOAD_LOCAL, 0),
            Instruction(Opcode.STORE_GLOBAL, "answer"),
            Instruction(Opcode.LOAD_GLOBAL, "answer"),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=(42,),
        local_count=1,
    )
    result = VirtualMachine().execute(module)
    assert result.output == ("42",)
    assert result.globals["answer"] == 42


def test_can_read_initial_globals():
    module = make_module(
        [
            Instruction(Opcode.LOAD_GLOBAL, "seed"),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ]
    )
    result = VirtualMachine().execute(module, initial_globals={"seed": 9})
    assert result.output == ("9",)


def test_executes_conditional_jump():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.JUMP_IF_FALSE, 4),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=(False, "unreachable"),
    )
    assert VirtualMachine().execute(module).output == ()


def test_executes_unconditional_jump():
    module = make_module(
        [
            Instruction(Opcode.JUMP, 2),
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.HALT),
        ],
        constants=(100,),
    )
    assert VirtualMachine().execute(module).final_stack == ()


def test_executes_boolean_and_comparison_operations():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.LESS),
            Instruction(Opcode.NOT),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=(2, 5),
    )
    assert VirtualMachine().execute(module).output == ("false",)


def test_rejects_division_by_zero():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.DIVIDE),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=(1, 0),
    )
    with pytest.raises(VMRuntimeError, match="Division by zero"):
        VirtualMachine().execute(module)


def test_rejects_uninitialized_local():
    module = make_module(
        [
            Instruction(Opcode.LOAD_LOCAL, 0),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        local_count=1,
    )
    with pytest.raises(VMRuntimeError, match="before initialization"):
        VirtualMachine().execute(module)


def test_rejects_undefined_global():
    module = make_module(
        [
            Instruction(Opcode.LOAD_GLOBAL, "missing"),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ]
    )
    with pytest.raises(VMRuntimeError, match="Undefined global"):
        VirtualMachine().execute(module)


def test_runtime_errors_retain_source_location():
    from rifai.bytecode import SourceLocation

    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.DIVIDE, location=SourceLocation(4, 8, 30, 31)),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        constants=(1, 0),
    )
    with pytest.raises(VMRuntimeError) as error:
        VirtualMachine().execute(module)
    assert error.value.diagnostic.line == 4
    assert error.value.diagnostic.column == 8


def test_instruction_budget_stops_infinite_jumps():
    module = make_module(
        [
            Instruction(Opcode.JUMP, 0),
            Instruction(Opcode.HALT),
        ]
    )
    with pytest.raises(VMRuntimeError, match="Instruction limit"):
        VirtualMachine(max_steps=7).execute(module)


def test_stack_limit_is_enforced():
    module = make_module(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.DUP),
            Instruction(Opcode.POP),
            Instruction(Opcode.POP),
            Instruction(Opcode.HALT),
        ],
        constants=(1,),
    )
    with pytest.raises(VMRuntimeError, match="Operand stack limit"):
        VirtualMachine(max_stack_depth=1).execute(module)
