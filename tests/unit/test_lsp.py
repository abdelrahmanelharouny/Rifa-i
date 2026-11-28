from __future__ import annotations

import json
from io import BytesIO

from rifai.lsp import (
    KEYWORDS,
    TYPES,
    LanguageServer,
    _offset_at,
    _position_at,
    read_message,
    serve,
    write_message,
)

SOURCE = """fn sum(a: int, b: int) -> int {
    return a + b;
}
let answer: int = sum(1, 2);
print(answer);
"""


def _open(server: LanguageServer, source: str = SOURCE, version: int = 1) -> str:
    uri = "file:///workspace/main.rif"
    server.handle_notification(
        "textDocument/didOpen",
        {"textDocument": {"uri": uri, "languageId": "rifai", "version": version, "text": source}},
    )
    return uri


def _position(source: str, substring: str, occurrence: int = 0) -> dict[str, int]:
    start = -1
    for _ in range(occurrence + 1):
        start = source.index(substring, start + 1)
    return _position_at(source, start)


def _params(uri: str, position: dict[str, int]) -> dict:
    return {"textDocument": {"uri": uri}, "position": position}


def test_initialize_advertises_editor_features() -> None:
    server = LanguageServer()
    capabilities = server.handle_request("initialize", {})["capabilities"]
    assert capabilities["textDocumentSync"]["change"] == 1
    assert capabilities["completionProvider"]
    assert capabilities["hoverProvider"] is True
    assert capabilities["definitionProvider"] is True
    assert capabilities["referencesProvider"] is True
    assert capabilities["documentSymbolProvider"] is True
    assert capabilities["signatureHelpProvider"]


def test_open_document_publishes_live_semantic_diagnostics() -> None:
    server = LanguageServer()
    uri = _open(server, "let answer: int = true;\n")
    notifications = server.take_notifications()
    assert notifications[0]["method"] == "textDocument/publishDiagnostics"
    payload = notifications[0]["params"]
    assert payload["uri"] == uri
    assert payload["diagnostics"]
    assert payload["diagnostics"][0]["code"] == "semantic"


def test_completion_hover_definition_and_references() -> None:
    server = LanguageServer()
    uri = _open(server)

    position = _position(SOURCE, "sum(1, 2)")
    completion = server.handle_request(
        "textDocument/completion", _params(uri, _position_at(SOURCE, SOURCE.index("sum(1") + 3))
    )
    assert any(item.get("filterText") == "sum" for item in completion["items"])

    hover = server.handle_request("textDocument/hover", _params(uri, position))
    assert hover is not None
    assert "sum(a: int, b: int) -> int" in hover["contents"]["value"]

    definition = server.handle_request("textDocument/definition", _params(uri, position))
    assert len(definition) == 1
    definition_start = definition[0]["range"]["start"]
    assert definition_start == _position_at(SOURCE, SOURCE.index("sum("))

    references = server.handle_request(
        "textDocument/references",
        {**_params(uri, position), "context": {"includeDeclaration": True}},
    )
    assert len(references) == 2



def test_generic_functions_receive_live_semantic_diagnostics_and_signature_help() -> None:
    source = """fn identity<T>(value: T) -> T { return value; }\nlet answer = identity(5);\n"""
    server = LanguageServer()
    uri = _open(server, source)
    assert server.documents[uri].analysis.diagnostics == ()
    position = _position(source, "identity(5)")
    hover = server.handle_request("textDocument/hover", _params(uri, position))
    assert hover is not None
    assert "int" in hover["contents"]["value"]

def test_document_symbols_include_functions_and_globals() -> None:
    server = LanguageServer()
    uri = _open(server)
    symbols = server.handle_request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
    assert [item["name"] for item in symbols] == ["sum", "answer"]
    assert symbols[0]["kind"] == 12
    assert [child["name"] for child in symbols[0]["children"]] == ["a", "b"]


def test_signature_help_reports_parameter_at_cursor() -> None:
    source = SOURCE.replace("sum(1, 2)", "sum(1, 2)")
    server = LanguageServer()
    uri = _open(server, source)
    offset = source.index("2)") + 1
    help_result = server.handle_request(
        "textDocument/signatureHelp", _params(uri, _position_at(source, offset))
    )
    assert help_result is not None
    assert help_result["activeParameter"] == 1


def test_utf16_position_round_trip_with_non_bmp_unicode() -> None:
    source = 'let label: string = "😀";\nlet value: int = 7;\n'
    offset = source.index("value")
    position = _position_at(source, offset)
    assert position == {"line": 1, "character": 4}
    assert _offset_at(source, position) == offset


def test_stale_document_changes_are_ignored_and_close_clears_diagnostics() -> None:
    server = LanguageServer()
    uri = _open(server, "let value: int = 1;\n", version=5)
    server.handle_notification(
        "textDocument/didChange",
        {
            "textDocument": {"uri": uri, "version": 4},
            "contentChanges": [{"text": "let value: int = true;\n"}],
        },
    )
    assert server.documents[uri].source == "let value: int = 1;\n"

    server.handle_notification("textDocument/didClose", {"textDocument": {"uri": uri}})
    assert uri not in server.documents
    assert server.take_notifications()[-1]["params"]["diagnostics"] == []


def test_content_length_framing_uses_utf8_byte_length() -> None:
    stream = BytesIO()
    message = {"jsonrpc": "2.0", "method": "test", "params": {"text": "مرحبا"}}
    write_message(stream, message)
    stream.seek(0)
    body = read_message(stream)
    assert body is not None
    assert json.loads(body.decode("utf-8")) == message


def test_stdio_server_handles_initialize_open_and_exit() -> None:
    incoming = BytesIO()
    write_message(incoming, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    write_message(
        incoming,
        {"jsonrpc": "2.0", "method": "textDocument/didOpen",
         "params": {"textDocument": {"uri": "file:///main.rif", "version": 1, "text": SOURCE}}},
    )
    write_message(incoming, {"jsonrpc": "2.0", "method": "exit"})
    incoming.seek(0)

    outgoing = BytesIO()
    assert serve(incoming, outgoing) == 0
    outgoing.seek(0)
    responses = []
    while (body := read_message(outgoing)) is not None:
        responses.append(json.loads(body.decode("utf-8")))
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "Rifa'i Language Server"
    assert any(item.get("method") == "textDocument/publishDiagnostics" for item in responses)


def test_completion_includes_typed_collection_syntax_and_builtins() -> None:
    server = LanguageServer()
    uri = _open(server, "")
    result = server.handle_request(
        "textDocument/completion",
        {
            "textDocument": {"uri": uri},
            "position": {"line": 0, "character": 0},
        },
    )
    labels = {item["label"] for item in result.get("items", [])}
    assert {"len", "push", "pop"} <= set(KEYWORDS)
    assert {"int[]", "float[]", "bool[]", "string[]"} <= set(TYPES)
    assert {"len", "push", "pop", "int[]", "float[]", "bool[]", "string[]"} <= labels
