"""Versioned, deterministic serialization for Rifa'i .rbc files."""

from __future__ import annotations

import json
import math
from pathlib import Path

from rifai.bytecode.chunk import CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode, SourceLocation
from rifai.bytecode.module import BytecodeModule, FORMAT_VERSION, MAGIC, is_constant

MAX_BYTECODE_SIZE = 16 * 1024 * 1024


class BytecodeFormatError(ValueError):
    """Raised when a bytecode file is malformed or uses an unsupported format."""


def _constant_to_json(value: object) -> dict[str, object]:
    if type(value) is bool:
        return {"type": "bool", "value": value}
    if type(value) is int:
        return {"type": "int", "value": value}
    if type(value) is float and math.isfinite(value):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    raise BytecodeFormatError(f"Unsupported constant value: {value!r}.")


def _constant_from_json(raw: object) -> int | float | bool | str:
    if not isinstance(raw, dict) or set(raw) != {"type", "value"}:
        raise BytecodeFormatError("Malformed constant pool entry.")
    kind, value = raw["type"], raw["value"]
    if kind == "bool" and type(value) is bool:
        return value
    if kind == "int" and type(value) is int:
        return value
    if kind == "float" and type(value) in (int, float) and math.isfinite(value):
        return float(value)
    if kind == "string" and isinstance(value, str):
        return value
    raise BytecodeFormatError("Constant entry type and value do not match.")


def _location_to_json(location: SourceLocation | None) -> dict[str, int] | None:
    if location is None:
        return None
    return {
        "line": location.line,
        "column": location.column,
        "start_offset": location.start_offset,
        "end_offset": location.end_offset,
    }


def _location_from_json(raw: object) -> SourceLocation | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BytecodeFormatError("Instruction source location must be an object or null.")
    required = {"line", "column", "start_offset", "end_offset"}
    if set(raw) != required:
        raise BytecodeFormatError("Instruction source location has invalid fields.")
    values = [raw[key] for key in ("line", "column", "start_offset", "end_offset")]
    if any(type(value) is not int for value in values):
        raise BytecodeFormatError("Source location coordinates must be integers.")
    line, column, start, end = values
    if line < 1 or column < 1 or start < 0 or end < start:
        raise BytecodeFormatError("Source location coordinates are out of range.")
    return SourceLocation(line, column, start, end)


def _chunk_to_json(chunk: CodeChunk) -> dict[str, object]:
    return {
        "name": chunk.name,
        "arity": chunk.arity,
        "local_count": chunk.local_count,
        "instructions": [
            {
                "opcode": instruction.opcode.value,
                "operand": instruction.operand,
                "location": _location_to_json(instruction.location),
            }
            for instruction in chunk.instructions
        ],
    }


def _chunk_from_json(raw: object) -> CodeChunk:
    if not isinstance(raw, dict) or set(raw) != {
        "name", "arity", "local_count", "instructions"
    }:
        raise BytecodeFormatError("Malformed main code chunk.")
    name, arity, local_count, raw_instructions = (
        raw["name"], raw["arity"], raw["local_count"], raw["instructions"]
    )
    if not isinstance(name, str):
        raise BytecodeFormatError("Chunk name must be a string.")
    if type(arity) is not int or type(local_count) is not int:
        raise BytecodeFormatError("Chunk arity and local_count must be integers.")
    if not isinstance(raw_instructions, list):
        raise BytecodeFormatError("Chunk instructions must be an array.")

    instructions: list[Instruction] = []
    for index, item in enumerate(raw_instructions):
        if not isinstance(item, dict) or set(item) != {"opcode", "operand", "location"}:
            raise BytecodeFormatError(f"Malformed instruction at index {index}.")
        opcode_name = item["opcode"]
        if not isinstance(opcode_name, str):
            raise BytecodeFormatError(f"Invalid opcode at instruction {index}.")
        try:
            opcode = Opcode(opcode_name)
        except ValueError as exc:
            raise BytecodeFormatError(
                f"Unknown opcode {opcode_name!r} at instruction {index}."
            ) from exc
        operand = item["operand"]
        if operand is not None and type(operand) not in (int, str):
            raise BytecodeFormatError(f"Invalid operand at instruction {index}.")
        instructions.append(
            Instruction(
                opcode=opcode,
                operand=operand,
                location=_location_from_json(item["location"]),
            )
        )
    return CodeChunk(
        name=name,
        instructions=tuple(instructions),
        local_count=local_count,
        arity=arity,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BytecodeFormatError(f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


class BytecodeSerializer:
    """Encode and decode the Rifa'i versioned bytecode container."""

    @staticmethod
    def to_bytes(module: BytecodeModule) -> bytes:
        if not isinstance(module, BytecodeModule):
            raise TypeError("module must be a BytecodeModule.")
        if module.format_version != FORMAT_VERSION:
            raise BytecodeFormatError(
                f"Cannot write bytecode version {module.format_version}; "
                f"writer supports version {FORMAT_VERSION}."
            )
        if any(not is_constant(value) for value in module.constants):
            raise BytecodeFormatError("Module contains an unsupported constant.")

        try:
            payload = {
                "magic": "RIFAI",
                "format_version": module.format_version,
                "source_name": module.source_name,
                "constants": [_constant_to_json(value) for value in module.constants],
                "main": _chunk_to_json(module.main),
            }
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (AttributeError, TypeError, ValueError, UnicodeEncodeError) as exc:
            if isinstance(exc, BytecodeFormatError):
                raise
            raise BytecodeFormatError(f"Unable to serialize bytecode: {exc}") from exc

        data = MAGIC + encoded
        if len(data) > MAX_BYTECODE_SIZE:
            raise BytecodeFormatError("Bytecode module exceeds the maximum file size.")
        return data

    @staticmethod
    def from_bytes(data: bytes) -> BytecodeModule:
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes.")
        if len(data) > MAX_BYTECODE_SIZE:
            raise BytecodeFormatError("Bytecode module exceeds the maximum file size.")
        if not data.startswith(MAGIC):
            raise BytecodeFormatError("Invalid Rifa'i bytecode magic header.")
        try:
            payload = json.loads(
                data[len(MAGIC):].decode("utf-8"),
                object_pairs_hook=_unique_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise BytecodeFormatError(f"Invalid bytecode payload: {exc}") from exc

        if not isinstance(payload, dict) or set(payload) != {
            "magic", "format_version", "source_name", "constants", "main"
        }:
            raise BytecodeFormatError("Bytecode module has an invalid top-level structure.")
        if payload["magic"] != "RIFAI":
            raise BytecodeFormatError("Bytecode magic identifier does not match.")
        version = payload["format_version"]
        if type(version) is not int or version != FORMAT_VERSION:
            raise BytecodeFormatError(
                f"Unsupported bytecode version {version!r}; "
                f"supported version is {FORMAT_VERSION}."
            )
        source_name = payload["source_name"]
        if source_name is not None and not isinstance(source_name, str):
            raise BytecodeFormatError("source_name must be a string or null.")
        raw_constants = payload["constants"]
        if not isinstance(raw_constants, list):
            raise BytecodeFormatError("Constant pool must be an array.")

        constants = tuple(_constant_from_json(item) for item in raw_constants)
        main = _chunk_from_json(payload["main"])
        return BytecodeModule(
            constants=constants,
            main=main,
            source_name=source_name,
            format_version=version,
        )

    @classmethod
    def write(cls, module: BytecodeModule, path: str | Path) -> None:
        target = Path(path)
        target.write_bytes(cls.to_bytes(module))

    @classmethod
    def read(cls, path: str | Path) -> BytecodeModule:
        target = Path(path)
        size = target.stat().st_size
        if size > MAX_BYTECODE_SIZE:
            raise BytecodeFormatError("Bytecode module exceeds the maximum file size.")
        return cls.from_bytes(target.read_bytes())
