"""Integration tests for the Rifa'i CLI (`tokens`, `parse`, `ast`, `check`)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rifai.cli import main


def test_cli_tokens_on_valid_example_file(capsys: object) -> None:
    example_path = Path("examples/hello.rif")
    exit_code = main(["tokens", str(example_path)])
    assert exit_code == 0

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "FN" in captured.out
    assert "ARROW" in captured.out
    assert "EOF" in captured.out
    assert captured.err == ""


def test_cli_tokens_reports_lexical_errors_with_nonzero_exit(
    tmp_path: Path, capsys: object
) -> None:
    bad_file = tmp_path / "bad.rif"
    bad_file.write_text("let x: int = @;\n", encoding="utf-8")

    exit_code = main(["tokens", str(bad_file)])
    assert exit_code == 1

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "LET" in captured.out
    assert "[lexer]" in captured.err
    assert "1:14" in captured.err


def test_cli_tokens_missing_file_returns_nonzero(
    tmp_path: Path, capsys: object
) -> None:
    missing = tmp_path / "does_not_exist.rif"
    exit_code = main(["tokens", str(missing)])
    assert exit_code == 1

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "[io]" in captured.err


def test_cli_parse_ast_and_check_on_valid_example(capsys: object) -> None:
    example_path = Path("examples/hello.rif")

    assert main(["parse", str(example_path)]) == 0
    out_parse = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Parsing succeeded" in out_parse.out
    assert out_parse.err == ""

    assert main(["ast", str(example_path)]) == 0
    out_ast = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Program" in out_ast.out
    assert "FunctionDeclaration add" in out_ast.out
    assert out_ast.err == ""

    assert main(["check", str(example_path)]) == 0
    out_check = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Semantic check passed" in out_check.out
    assert out_check.err == ""


def test_cli_parse_and_check_error_exit_codes(tmp_path: Path, capsys: object) -> None:
    syntax_bad = tmp_path / "syntax_bad.rif"
    syntax_bad.write_text("let x: int = ;\n", encoding="utf-8")

    assert main(["parse", str(syntax_bad)]) == 1
    assert "[parser]" in capsys.readouterr().err  # type: ignore[attr-defined]

    assert main(["ast", str(syntax_bad)]) == 1
    assert "[parser]" in capsys.readouterr().err  # type: ignore[attr-defined]

    # `check` stops after parser errors and does not run semantic analysis
    assert main(["check", str(syntax_bad)]) == 1
    err_check_syntax = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "[parser]" in err_check_syntax
    assert "[semantic]" not in err_check_syntax

    sem_bad = tmp_path / "sem_bad.rif"
    sem_bad.write_text('let x: int = "wrong";\n', encoding="utf-8")
    assert main(["parse", str(sem_bad)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]

    assert main(["check", str(sem_bad)]) == 1
    assert "[semantic]" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_python_module_invocation_on_example() -> None:
    env = os.environ.copy()
    src_path = str(Path("src").resolve())
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing}" if existing else src_path

    proc = subprocess.run(
        [sys.executable, "-m", "rifai", "tokens", "examples/hello.rif"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert "STRING" in proc.stdout
    assert "Rifa'i" in proc.stdout
    assert proc.stderr == ""
