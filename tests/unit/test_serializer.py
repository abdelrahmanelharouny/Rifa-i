import pytest

from rifai.bytecode import (
    BytecodeFormatError,
    BytecodeModule,
    BytecodeSerializer,
    CodeChunk,
    Instruction,
    Opcode,
    SourceLocation,
)


def sample_module():
    return BytecodeModule(
        constants=(17, 2.5, True, "Rifa'i"),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CONSTANT, 0, SourceLocation(1, 1, 0, 2)),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
        source_name="examples/sample.rif",
    )


def test_round_trip_preserves_constants_instructions_and_source_map():
    original = sample_module()
    encoded = BytecodeSerializer.to_bytes(original)
    decoded = BytecodeSerializer.from_bytes(encoded)
    assert decoded == original


def test_serialization_is_deterministic():
    module = sample_module()
    assert BytecodeSerializer.to_bytes(module) == BytecodeSerializer.to_bytes(module)


def test_file_round_trip(tmp_path):
    path = tmp_path / "program.rbc"
    BytecodeSerializer.write(sample_module(), path)
    loaded = BytecodeSerializer.read(path)
    assert loaded == sample_module()


def test_rejects_invalid_magic():
    with pytest.raises(BytecodeFormatError, match="magic"):
        BytecodeSerializer.from_bytes(b"NOT-RBC{}")


def test_rejects_malformed_json():
    from rifai.bytecode.module import MAGIC

    with pytest.raises(BytecodeFormatError, match="payload"):
        BytecodeSerializer.from_bytes(MAGIC + b"{broken")


def test_rejects_unsupported_version():
    import json
    from rifai.bytecode.module import MAGIC

    payload = {
        "magic": "RIFAI",
        "format_version": 99,
        "source_name": None,
        "constants": [],
        "main": {
            "name": "<main>",
            "arity": 0,
            "local_count": 0,
            "instructions": [{"opcode": "HALT", "operand": None, "location": None}],
        },
    }
    with pytest.raises(BytecodeFormatError, match="Unsupported bytecode version"):
        BytecodeSerializer.from_bytes(MAGIC + json.dumps(payload).encode())


def test_rejects_unknown_opcode():
    import json
    from rifai.bytecode.module import MAGIC

    payload = {
        "magic": "RIFAI",
        "format_version": 1,
        "source_name": None,
        "constants": [],
        "main": {
            "name": "<main>",
            "arity": 0,
            "local_count": 0,
            "instructions": [{"opcode": "RUN_NATIVE", "operand": None, "location": None}],
        },
    }
    with pytest.raises(BytecodeFormatError, match="Unknown opcode"):
        BytecodeSerializer.from_bytes(MAGIC + json.dumps(payload).encode())


def test_rejects_boolean_as_integer_operand():
    import json
    from rifai.bytecode.module import MAGIC

    payload = {
        "magic": "RIFAI",
        "format_version": 1,
        "source_name": None,
        "constants": [],
        "main": {
            "name": "<main>",
            "arity": 0,
            "local_count": 0,
            "instructions": [
                {"opcode": "JUMP", "operand": True, "location": None},
                {"opcode": "HALT", "operand": None, "location": None},
            ],
        },
    }
    with pytest.raises(BytecodeFormatError, match="Invalid operand"):
        BytecodeSerializer.from_bytes(MAGIC + json.dumps(payload).encode())


def test_rejects_duplicate_json_keys():
    from rifai.bytecode.module import MAGIC

    payload = (
        b'{"magic":"RIFAI","magic":"RIFAI","format_version":1,'
        b'"source_name":null,"constants":[],"main":{"name":"<main>",'
        b'"arity":0,"local_count":0,"instructions":['
        b'{"opcode":"HALT","operand":null,"location":null}]}}'
    )
    with pytest.raises(BytecodeFormatError, match="Duplicate JSON object key"):
        BytecodeSerializer.from_bytes(MAGIC + payload)


def test_reads_and_executes_legacy_version_one_modules():
    from rifai.bytecode import LEGACY_FORMAT_VERSION
    from rifai.vm import VirtualMachine

    legacy = BytecodeModule(
        constants=(42,),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
        format_version=LEGACY_FORMAT_VERSION,
    )
    encoded = BytecodeSerializer.to_bytes(legacy)
    decoded = BytecodeSerializer.from_bytes(encoded)
    assert decoded.format_version == LEGACY_FORMAT_VERSION
    assert decoded == legacy
    assert VirtualMachine().execute(decoded).output == ("42",)


def test_rejects_boolean_as_bytecode_format_version():
    from dataclasses import replace

    with pytest.raises(BytecodeFormatError, match="Cannot write bytecode version"):
        BytecodeSerializer.to_bytes(replace(sample_module(), format_version=True))
