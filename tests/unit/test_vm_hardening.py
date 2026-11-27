import pytest

from rifai.bytecode import BytecodeModule, CodeChunk, Instruction, Opcode
from rifai.vm import VMRuntimeError, VirtualMachine


def module_for(instructions, constants=()):
    return BytecodeModule(
        constants=tuple(constants),
        main=CodeChunk("<main>", tuple(instructions)),
    )


def test_vm_limits_require_positive_exact_integers():
    for name in (
        "max_steps",
        "max_stack_depth",
        "max_call_depth",
        "max_string_length",
        "max_output_chars",
        "max_integer_bits",
    ):
        with pytest.raises(ValueError, match="positive integer"):
            VirtualMachine(**{name: True})
        with pytest.raises(ValueError, match="positive integer"):
            VirtualMachine(**{name: 0})


def test_rejects_non_mapping_initial_globals():
    module = module_for([Instruction(Opcode.HALT)])
    with pytest.raises(TypeError, match="mapping"):
        VirtualMachine().execute(module, initial_globals=[("x", 1)])


def test_rejects_oversized_initial_global_strings():
    module = module_for([Instruction(Opcode.HALT)])
    with pytest.raises(ValueError, match="string length limit"):
        VirtualMachine(max_string_length=3).execute(
            module,
            initial_globals={"message": "four"},
        )


def test_string_concatenation_obeys_string_limit_before_allocating_result():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.ADD),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        ("abc", "def"),
    )
    with pytest.raises(VMRuntimeError, match="String length limit"):
        VirtualMachine(max_string_length=5).execute(module)


def test_captured_output_has_an_independent_total_limit():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        ("abc",),
    )
    with pytest.raises(VMRuntimeError, match="Captured output limit"):
        VirtualMachine(max_output_chars=5).execute(module)


def test_vm_rejects_integer_values_over_the_bit_limit():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (1 << 128,),
    )
    with pytest.raises(VMRuntimeError, match="Integer bit limit"):
        VirtualMachine(max_integer_bits=64).execute(module)


def test_vm_checks_integer_growth_before_multiplication():
    module = module_for(
        [
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.MULTIPLY),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
        ],
        (1 << 100, 1 << 100),
    )
    with pytest.raises(VMRuntimeError, match="Integer bit limit"):
        VirtualMachine(max_integer_bits=128).execute(module)


def test_initial_globals_obey_integer_bit_limit():
    module = module_for([Instruction(Opcode.HALT)])
    with pytest.raises(ValueError, match="integer bit limit"):
        VirtualMachine(max_integer_bits=32).execute(
            module,
            initial_globals={"seed": 1 << 64},
        )
