from __future__ import annotations

import json
import socket
from threading import Thread

from rifai.bytecode import BytecodeSerializer
from rifai.compiler import Compiler
from rifai.vm.dap import RifaIDebugAdapter


def _read_message(stream):
    headers = {}
    while True:
        line = stream.readline()
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii").partition(":")
        headers[name.lower()] = value.strip()
    length = int(headers["content-length"])
    return json.loads(stream.read(length).decode("utf-8"))


def _send_request(writer, sequence, command, arguments=None):
    payload = json.dumps({
        "seq": sequence,
        "type": "request",
        "command": command,
        "arguments": arguments or {},
    }).encode("utf-8")
    writer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
    writer.flush()


def _request(writer, reader, sequence, command, arguments=None):
    _send_request(writer, sequence, command, arguments)
    while True:
        message = _read_message(reader)
        if message.get("type") == "response" and message.get("request_seq") == sequence:
            return message


def _event(reader, name):
    while True:
        message = _read_message(reader)
        if message.get("type") == "event" and message.get("event") == name:
            return message


def test_dap_debugs_standalone_rbc_and_exposes_embedded_source_and_locals(tmp_path):
    source_path = tmp_path / "standalone.rif"
    bytecode_path = tmp_path / "standalone.rbc"
    source = "let answer: int = 40 + 2;\nprint(answer);\n"
    source_path.write_text(source, encoding="utf-8")
    compiled = Compiler().compile(source, source_name=str(source_path))
    assert compiled.is_success and compiled.module is not None
    BytecodeSerializer.write(compiled.module, bytecode_path)
    source_path.unlink()

    server_socket, client_socket = socket.socketpair()
    server_reader = server_socket.makefile("rb")
    server_writer = server_socket.makefile("wb")
    client_reader = client_socket.makefile("rb")
    client_writer = client_socket.makefile("wb")
    client_socket.settimeout(5)
    results = []
    adapter = RifaIDebugAdapter(server_reader, server_writer)
    worker = Thread(target=lambda: results.append(adapter.run()), daemon=True)
    worker.start()

    try:
        assert _request(client_writer, client_reader, 1, "initialize")["success"]
        assert _request(
            client_writer,
            client_reader,
            2,
            "launch",
            {"program": str(bytecode_path), "stopOnEntry": True},
        )["success"]
        assert _event(client_reader, "initialized")["event"] == "initialized"

        breakpoint_response = _request(
            client_writer,
            client_reader,
            3,
            "setBreakpoints",
            {
                "source": {"name": "standalone.rif", "path": str(source_path)},
                "breakpoints": [{"line": 1}],
            },
        )
        assert breakpoint_response["body"]["breakpoints"][0]["verified"] is True

        assert _request(client_writer, client_reader, 4, "configurationDone")["success"]
        stopped = _event(client_reader, "stopped")
        assert stopped["body"]["reason"] == "entry"

        stack = _request(client_writer, client_reader, 5, "stackTrace", {"threadId": 1})
        assert stack["body"]["stackFrames"][0]["name"] == "<main>"
        frame_id = stack["body"]["stackFrames"][0]["id"]

        scopes = _request(client_writer, client_reader, 6, "scopes", {"frameId": frame_id})
        locals_ref = scopes["body"]["scopes"][0]["variablesReference"]
        variables = _request(
            client_writer,
            client_reader,
            7,
            "variables",
            {"variablesReference": locals_ref},
        )
        answer = next(item for item in variables["body"]["variables"] if item["name"] == "answer")
        assert answer["type"] == "int"
        assert answer["value"] == "<uninitialized>"

        loaded_source = _request(
            client_writer, client_reader, 8, "source", {"sourceReference": 1}
        )
        assert loaded_source["body"]["content"] == source

        assert _request(client_writer, client_reader, 9, "continue", {"threadId": 1})["success"]
        assert _event(client_reader, "continued")["event"] == "continued"
        assert _event(client_reader, "terminated")["event"] == "terminated"

        assert _request(client_writer, client_reader, 10, "disconnect")["success"]
        worker.join(timeout=3)
        assert not worker.is_alive()
        assert results == [0]
    finally:
        client_writer.close()
        client_reader.close()
        server_writer.close()
        server_reader.close()
        client_socket.close()
        server_socket.close()


def test_dap_rejects_invalid_content_length():
    import io

    adapter = RifaIDebugAdapter(
        io.BytesIO(b"Content-Type: application/json\r\n\r\n{}"),
        io.BytesIO(),
    )
    try:
        adapter._read_message()
    except ValueError as exc:
        assert "Content-Length" in str(exc)
    else:
        raise AssertionError("Expected malformed DAP frame to be rejected")
