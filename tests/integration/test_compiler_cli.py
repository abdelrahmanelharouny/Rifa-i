from rifai.bytecode import BytecodeSerializer
from rifai.cli import main


def test_compile_command_writes_rbc_file(tmp_path, capsys):
    source = tmp_path / "hello.rif"
    source.write_text('print("hello");', encoding="utf-8")
    assert main(["compile", str(source)]) == 0
    output = source.with_suffix(".rbc")
    assert output.exists()
    assert "Compilation succeeded" in capsys.readouterr().out
    assert BytecodeSerializer.read(output)


def test_run_command_compiles_and_executes_rif_source(tmp_path, capsys):
    source = tmp_path / "hello.rif"
    source.write_text("""print("hello from Rifa'i");""", encoding="utf-8")
    assert main(["run", str(source)]) == 0
    assert capsys.readouterr().out.strip() == "hello from Rifa'i"


def test_run_command_executes_rbc_file(tmp_path, capsys):
    source = tmp_path / "answer.rif"
    source.write_text("print(6 * 7);", encoding="utf-8")
    assert main(["compile", str(source)]) == 0
    capsys.readouterr()
    assert main(["run", str(source.with_suffix(".rbc"))]) == 0
    assert capsys.readouterr().out.strip() == "42"


def test_compile_command_reports_invalid_source_and_does_not_write_output(tmp_path, capsys):
    source = tmp_path / "bad.rif"
    source.write_text("let x: int = false;", encoding="utf-8")
    assert main(["compile", str(source)]) == 1
    assert not source.with_suffix(".rbc").exists()
    assert "[semantic]" in capsys.readouterr().err


def test_compile_command_accepts_explicit_output_path(tmp_path, capsys):
    source = tmp_path / "source.rif"
    target = tmp_path / "build" / "program.rbc"
    target.parent.mkdir()
    source.write_text("print(42);", encoding="utf-8")
    assert main(["compile", str(source), "--output", str(target)]) == 0
    assert target.exists()
