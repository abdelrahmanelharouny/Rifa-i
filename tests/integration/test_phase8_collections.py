from rifai.cli import main


def test_run_command_compiles_and_executes_typed_arrays(tmp_path, capsys) -> None:
    source = tmp_path / "arrays.rif"
    source.write_text(
        "let values: int[] = [10, 20];\n"
        "push(values, 30);\n"
        "print(values[2]);\n",
        encoding="utf-8",
    )
    assert main(["run", str(source)]) == 0
    assert capsys.readouterr().out.strip() == "30"


def test_compile_command_emits_bytecode_v7_with_collections(tmp_path, capsys) -> None:
    import json
    from rifai.bytecode import BytecodeSerializer

    source = tmp_path / "arrays.rif"
    source.write_text("let values: int[] = [1, 2];\nprint(len(values));", encoding="utf-8")
    assert main(["compile", str(source)]) == 0
    capsys.readouterr()
    module = BytecodeSerializer.read(source.with_suffix(".rbc"))
    assert module.format_version == 7
    assert any(instruction.opcode.value == "ARRAY_NEW_INT" for instruction in module.main.instructions)
    assert any(instruction.opcode.value == "LENGTH" for instruction in module.main.instructions)
