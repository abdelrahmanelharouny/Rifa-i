from __future__ import annotations

from rifai.cli import main


def test_debug_cli_runs_program_after_continue_command(tmp_path, monkeypatch, capsys) -> None:
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


def test_debug_cli_rejects_bytecode_input(tmp_path, capsys) -> None:
    source = tmp_path / "program.rbc"
    source.write_bytes(b"")
    assert main(["debug", str(source)]) == 2
    assert "Expected a .rif source file" in capsys.readouterr().err


def test_debug_cli_rejects_breakpoints_outside_source(tmp_path, capsys) -> None:
    source = tmp_path / "hello.rif"
    source.write_text("print(42);\n", encoding="utf-8")
    assert main(["debug", str(source), "--breakpoint", "5"]) == 2
    assert "outside the source file" in capsys.readouterr().err
