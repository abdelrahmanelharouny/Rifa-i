from rifai.bytecode import Opcode
from rifai.compiler import Compiler
from rifai.vm import VirtualMachine


def test_constant_propagation_folds_branches_and_removes_dead_blocks():
    source = """let base: int = 5;
let result: int = base + 2;
if (result == 7) {
    print(result + 1);
} else {
    print(999);
}
"""
    optimized = Compiler(optimize=True).compile(source)
    unoptimized = Compiler(optimize=False).compile(source)

    assert optimized.is_success and unoptimized.is_success
    assert VirtualMachine().execute(optimized.module).output == ("8",)
    assert VirtualMachine().execute(unoptimized.module).output == ("8",)
    assert optimized.optimization.constant_loads_propagated >= 2
    assert optimized.optimization.branches_folded >= 1
    assert optimized.optimization.unreachable_instructions_removed >= 1
    assert not any(
        item.opcode is Opcode.JUMP_IF_FALSE
        for item in optimized.module.main.instructions
    )


def test_global_constants_are_invalidated_by_function_calls():
    source = """let value: int = 1;
fn change() -> void {
    value = 2;
}
change();
print(value);
"""
    compiled = Compiler().compile(source)

    assert compiled.is_success
    assert VirtualMachine().execute(compiled.module).output == ("2",)
    call_index = next(
        index for index, instruction in enumerate(compiled.module.main.instructions)
        if instruction.opcode is Opcode.CALL
    )
    assert any(
        instruction.opcode is Opcode.LOAD_GLOBAL and instruction.operand == "value"
        for instruction in compiled.module.main.instructions[call_index + 1:]
    )


def test_loop_dataflow_does_not_assume_a_single_iteration_value():
    source = """let counter: int = 0;
while (counter < 3) {
    counter = counter + 1;
}
print(counter);
"""
    optimized = Compiler(optimize=True).compile(source)
    unoptimized = Compiler(optimize=False).compile(source)

    assert optimized.is_success and unoptimized.is_success
    assert VirtualMachine().execute(optimized.module).output == ("3",)
    assert VirtualMachine().execute(unoptimized.module).output == ("3",)


def test_common_subexpression_elimination_reuses_profitable_local_expression():
    source = """fn calculate(a: int, b: int, c: int, d: int) -> int {
    let first: int = (a + b) * (c + d);
    let second: int = (a + b) * (c + d);
    return first + second;
}
print(calculate(1, 2, 3, 4));
"""
    optimized = Compiler(optimize=True).compile(source)
    unoptimized = Compiler(optimize=False).compile(source)

    assert optimized.is_success and unoptimized.is_success
    assert VirtualMachine().execute(optimized.module).output == ("42",)
    assert VirtualMachine().execute(unoptimized.module).output == ("42",)
    assert optimized.optimization.common_subexpressions_eliminated >= 1
    optimized_function = optimized.module.functions[0].chunk
    original_function = unoptimized.module.functions[0].chunk
    assert optimized_function.local_count > original_function.local_count
    assert len(optimized_function.instructions) < len(original_function.instructions)
    debug_names = optimized.module.debug_info.as_mapping()["calculate"]
    assert any(name.startswith("_cse_tmp_") for name, _ in debug_names.values())


def test_common_subexpression_cache_is_invalidated_by_local_assignment():
    source = """fn calculate(a: int, b: int, c: int) -> int {
    let first: int = (a + b) * c;
    a = a + 1;
    let second: int = (a + b) * c;
    return first + second;
}
print(calculate(1, 2, 3));
"""
    optimized = Compiler(optimize=True).compile(source)
    unoptimized = Compiler(optimize=False).compile(source)

    assert optimized.is_success and unoptimized.is_success
    assert VirtualMachine().execute(optimized.module).output == ("21",)
    assert VirtualMachine().execute(unoptimized.module).output == ("15",)
    assert optimized.optimization.common_subexpressions_eliminated == 0


def test_optimizer_remains_idempotent_after_dataflow_and_cse():
    from rifai.bytecode.optimizer import BytecodeOptimizer

    source = """fn calculate(a: int, b: int, c: int, d: int) -> int {
    let first: int = (a + b) * (c + d);
    let second: int = (a + b) * (c + d);
    return first + second;
}
print(calculate(1, 2, 3, 4));
"""
    compiled = Compiler().compile(source)
    second = BytecodeOptimizer().optimize(compiled.module)

    assert second.module == compiled.module
    assert second.stats.common_subexpressions_eliminated == 0
