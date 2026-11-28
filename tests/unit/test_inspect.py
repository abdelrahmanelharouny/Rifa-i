from __future__ import annotations

import json

from rifai.inspect import inspect_source

PROGRAM = """fn twice(value: int) -> int {
    return value * 2;
}
let result: int = twice(21);
print(result);
"""


def test_inspect_exports_all_pipeline_stages_as_json_safe_data() -> None:
    snapshot = inspect_source(PROGRAM, source_name="sample.rif")
    assert snapshot["success"] is True
    assert snapshot["schema_version"] == 1
    assert snapshot["stages"]["lexer"]["token_count"] > 0
    assert snapshot["stages"]["parser"]["ast"]["kind"] == "Program"
    assert snapshot["stages"]["semantic"]["global_symbols"]
    assert snapshot["stages"]["ir"]["ir_version"] == 1
    assert snapshot["stages"]["ir"]["stats"]["blocks"] > 0
    assert snapshot["stages"]["ir_pipeline"]["passes"]
    assert snapshot["stages"]["ir_analysis"]["functions"]["<main>"]["dominators"]
    bytecode = snapshot["stages"]["bytecode"]
    assert bytecode["format_version"] == 6
    assert bytecode["functions"][0]["name"] == "twice"
    assert bytecode["disassembly"].startswith("Rifa'i Bytecode")
    assert bytecode["optimization"] is not None
    assert bytecode["control_flow"]["<main>"]["block_count"] > 0
    assert bytecode["control_flow"]["twice"]["reachable_blocks"]
    json.dumps(snapshot, ensure_ascii=False)


def test_inspect_reports_frontend_errors_without_claiming_success() -> None:
    snapshot = inspect_source("let value: int = true;\n")
    assert snapshot["success"] is False
    assert snapshot["diagnostics"]
    assert snapshot["diagnostics"][0]["phase"] == "semantic"
    assert "bytecode" not in snapshot["stages"]


def test_inspect_can_export_unoptimized_bytecode() -> None:
    optimized = inspect_source(PROGRAM, optimize=True)
    unoptimized = inspect_source(PROGRAM, optimize=False)
    assert optimized["success"] and unoptimized["success"]
    assert optimized["stages"]["bytecode"]["optimization"] is not None
    assert unoptimized["stages"]["bytecode"]["optimization"] is None
