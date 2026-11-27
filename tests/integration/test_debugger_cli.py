from rifai.cli import main


def test_debug_cli_runs_source_program_after_continue(tmp_path, monkeypatch, capsys) -> None:
    source = tmp_path / "hello.rif"
    source.write_text('print("debugged");\n', encoding="utf-8")
    commands = iter(["continue"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))

    assert main(["debug", str(source)]) == 0
    output = capsys.readouterr().out
    assert "Paused (entry)" in output
    assert "Program output:" in output
    assert "debugged" in output
    assert "Execution finished:" in output


def test_debug_cli_accepts_standalone_rbc_after_source_is_removed(
    tmp_path, monkeypatch, capsys
) -> None:
    source = tmp_path / "standalone.rif"
    source.write_text('let answer: int = 42;\nprint(answer);\n', encoding="utf-8")
    assert main(["compile", str(source)]) == 0
    capsys.readouterr()
    bytecode = source.with_suffix(".rbc")
    source.unlink()

    commands = iter(["continue", "globals", "continue"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert main(["debug", str(bytecode), "--breakpoint", "2"]) == 0
    output = capsys.readouterr().out
    assert "Paused (entry)" in output
    assert "answer" in output
    assert "42" in output
    assert "Execution finished:" in output


def test_debug_cli_rejects_unsupported_input(tmp_path, capsys) -> None:
    path = tmp_path / "program.txt"
    path.write_text("not a program", encoding="utf-8")
    assert main(["debug", str(path)]) == 2
    assert "Expected a .rif source or .rbc bytecode file" in capsys.readouterr().err


def test_debug_cli_rejects_breakpoints_outside_source(tmp_path, capsys) -> None:
    source = tmp_path / "hello.rif"
    source.write_text("print(42);\n", encoding="utf-8")
    assert main(["debug", str(source), "--breakpoint", "5"]) == 2
    assert "outside the source file" in capsys.readouterr().err
