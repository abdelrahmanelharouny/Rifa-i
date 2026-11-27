from __future__ import annotations

import json

from rifai.cli import main


def test_inspect_cli_writes_json_report(tmp_path) -> None:
    source = tmp_path / "hello.rif"
    report = tmp_path / "hello.inspect.json"
    source.write_text('let answer: int = 42;\nprint(answer);\n', encoding="utf-8")

    assert main(["inspect", str(source), "--output", str(report)]) == 0
    snapshot = json.loads(report.read_text(encoding="utf-8"))
    assert snapshot["success"] is True
    assert snapshot["source_name"] == str(source)


def test_inspect_cli_rejects_non_rif_input(tmp_path) -> None:
    source = tmp_path / "hello.txt"
    source.write_text("not a program", encoding="utf-8")
    assert main(["inspect", str(source)]) == 2
