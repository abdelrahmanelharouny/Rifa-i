import pytest

from rifai.bytecode import BytecodeSerializer, BytecodeVerifier, Opcode
from rifai.compiler import Compiler
from rifai.vm import VMRuntimeError, VirtualMachine


def compile_ok(source, name="test.rif"):
    result = Compiler().compile(source, source_name=name)
    assert result.is_success, [diagnostic.format(name) for diagnostic in result.diagnostics]
    assert result.module is not None
    assert BytecodeVerifier().verify(result.module).is_valid
    return result.module


def test_compiles_and_runs_arithmetic_variables_and_print():
    module = compile_ok(
        """
        let x: int = 10;
        let y: int = 32;
        let answer: int = x + y;
        print(answer);
        """
    )
    result = VirtualMachine().execute(module)
    assert result.output == ("42",)
    assert result.globals["answer"] == 42


def test_compiles_nested_expression_precedence_and_unary_operators():
    module = compile_ok(
        """
        let value: int = -(2 + 3) * 4;
        let enabled: bool = not false and (value < 0);
        print(value);
        print(enabled);
        """
    )
    assert VirtualMachine().execute(module).output == ("-20", "true")


def test_compiles_if_else_and_else_if_chains():
    module = compile_ok(
        """
        let score: int = 75;
        if (score >= 90) {
            print("A");
        } else if (score >= 70) {
            print("B");
        } else {
            print("C");
        }
        """
    )
    assert VirtualMachine().execute(module).output == ("B",)


def test_compiles_while_loop_and_assignments():
    module = compile_ok(
        """
        let count: int = 3;
        let total: int = 0;
        while (count > 0) {
            total = total + count;
            count = count - 1;
        }
        print(total);
        """
    )
    assert VirtualMachine().execute(module).output == ("6",)


def test_compiles_function_calls_and_local_parameters():
    module = compile_ok(
        """
        fn add(a: int, b: int) -> int {
            let result: int = a + b;
            return result;
        }
        print(add(20, 22));
        """
    )
    assert len(module.functions) == 1
    assert VirtualMachine().execute(module).output == ("42",)


def test_compiles_recursive_factorial():
    module = compile_ok(
        """
        fn factorial(n: int) -> int {
            if (n <= 1) {
                return 1;
            } else {
                return n * factorial(n - 1);
            }
        }
        print(factorial(6));
        """
    )
    assert VirtualMachine().execute(module).output == ("720",)


def test_compiles_mutual_recursion_and_forward_function_references():
    module = compile_ok(
        """
        fn is_even(n: int) -> bool {
            if (n == 0) {
                return true;
            } else {
                return is_odd(n - 1);
            }
        }
        fn is_odd(n: int) -> bool {
            if (n == 0) {
                return false;
            } else {
                return is_even(n - 1);
            }
        }
        print(is_even(12));
        print(is_odd(7));
        """
    )
    assert VirtualMachine().execute(module).output == ("true", "true")


def test_compiles_void_function_and_implicit_return():
    module = compile_ok(
        """
        fn announce(message: string) -> void {
            print(message);
        }
        announce("Rifa'i");
        """
    )
    assert VirtualMachine().execute(module).output == ("Rifa'i",)


def test_compiles_global_variable_access_inside_functions():
    module = compile_ok(
        """
        let base: int = 40;
        fn add_two() -> int {
            return base + 2;
        }
        print(add_two());
        """
    )
    assert VirtualMachine().execute(module).output == ("42",)


def test_compiles_nested_scope_shadowing_without_slot_collisions():
    module = compile_ok(
        """
        fn choose() -> int {
            let value: int = 1;
            {
                let value: int = 2;
                print(value);
            }
            return value;
        }
        print(choose());
        """
    )
    assert VirtualMachine().execute(module).output == ("2", "1")


def test_compiles_locals_declared_in_control_flow_blocks():
    module = compile_ok(
        """
        fn calculate(flag: bool) -> int {
            if (flag) {
                let result: int = 10;
                return result;
            } else {
                let result: int = 20;
                return result;
            }
        }
        print(calculate(true));
        print(calculate(false));
        """
    )
    assert VirtualMachine().execute(module).output == ("10", "20")


def test_compiles_string_concatenation_and_float_division():
    module = compile_ok(
        """
        let greeting: string = "Rifa'" + "i";
        let result: float = 10 / 4;
        print(greeting);
        print(result);
        """
    )
    assert VirtualMachine().execute(module).output == ("Rifa'i", "2.5")


def test_function_frame_preserves_caller_operand_stack():
    module = compile_ok(
        """
        fn double(value: int) -> int {
            return value * 2;
        }
        print(100 + double(21));
        """
    )
    assert VirtualMachine().execute(module).output == ("142",)


def test_serialized_function_bytecode_round_trips_and_executes():
    module = compile_ok(
        """
        fn square(value: int) -> int {
            return value * value;
        }
        print(square(9));
        """
    )
    restored = BytecodeSerializer.from_bytes(BytecodeSerializer.to_bytes(module))
    assert restored == module
    assert VirtualMachine().execute(restored).output == ("81",)


def test_compiler_returns_frontend_diagnostics_for_invalid_source():
    result = Compiler().compile("let answer: int = true;", source_name="invalid.rif")
    assert not result.is_success
    assert result.module is None
    assert result.diagnostics
    assert result.diagnostics[0].phase.value == "semantic"


def test_vm_enforces_call_depth_limit():
    module = compile_ok(
        """
        fn recurse(n: int) -> int {
            return recurse(n + 1);
        }
        print(recurse(0));
        """
    )
    with pytest.raises(VMRuntimeError, match="Call stack limit"):
        VirtualMachine(max_call_depth=8).execute(module)
