from rifai.compiler import Compiler


def test_compilation_result_exposes_module_and_success_state():
    result = Compiler().compile('print("ok");', source_name="inline.rif")
    assert result.is_success
    assert result.module is not None
    assert result.diagnostics == ()


def test_empty_program_compiles_to_halt_only():
    result = Compiler().compile("")
    assert result.is_success
    assert len(result.module.main.instructions) == 1
