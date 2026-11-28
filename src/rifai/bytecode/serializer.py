"""Versioned, deterministic serialization for Rifa'i .rbc files."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import tempfile

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode, SourceLocation
from rifai.bytecode.module import (
    BytecodeDebugInfo,
    BytecodeDebugLocal,
    BytecodeModule,
    COLLECTIONS_FORMAT_VERSION,
    NOMINAL_TYPES_FORMAT_VERSION,
    ALGEBRAIC_TYPES_FORMAT_VERSION,
    GENERIC_TYPES_FORMAT_VERSION,
    DEBUG_INFO_FORMAT_VERSION,
    FORMAT_VERSION,
    FUNCTIONS_FORMAT_VERSION,
    LEGACY_FORMAT_VERSION,
    MAGIC,
    is_constant,
)
from rifai.stdlib import BUILTIN_FUNCTIONS

MAX_BYTECODE_SIZE = 16 * 1024 * 1024
MAX_DEBUG_SOURCE_CHARS = 8 * 1024 * 1024


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
        raise BytecodeFormatError("Malformed code chunk.")
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


def _function_to_json(function: BytecodeFunction) -> dict[str, object]:
    return {
        "name": function.name,
        "parameter_types": list(function.parameter_types),
        "return_type": function.return_type,
        "chunk": _chunk_to_json(function.chunk),
    }


def _function_from_json(raw: object) -> BytecodeFunction:
    if not isinstance(raw, dict) or set(raw) != {
        "name", "parameter_types", "return_type", "chunk"
    }:
        raise BytecodeFormatError("Malformed function metadata.")
    name = raw["name"]
    parameter_types = raw["parameter_types"]
    return_type = raw["return_type"]
    if not isinstance(name, str):
        raise BytecodeFormatError("Function name must be a string.")
    if not isinstance(parameter_types, list) or any(
        not isinstance(item, str) for item in parameter_types
    ):
        raise BytecodeFormatError("Function parameter_types must be a string array.")
    if not isinstance(return_type, str):
        raise BytecodeFormatError("Function return_type must be a string.")
    return BytecodeFunction(
        name=name,
        chunk=_chunk_from_json(raw["chunk"]),
        parameter_types=tuple(parameter_types),
        return_type=return_type,
    )


def _valid_debug_type_name(value: str, *, allow_nominal: bool) -> bool:
    if value.endswith("[]"):
        return _valid_debug_type_name(value[:-2], allow_nominal=allow_nominal)
    if value in {"int", "float", "bool", "string"}:
        return True
    return (
        allow_nominal
        and value != "void"
        and value not in BUILTIN_FUNCTIONS
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is not None
    )


def _debug_info_to_json(
    info: BytecodeDebugInfo | None,
    *,
    allow_nominal: bool = False,
) -> dict[str, object] | None:
    if info is None:
        return None
    if not isinstance(info, BytecodeDebugInfo):
        raise BytecodeFormatError("Module debug_info has an invalid type.")
    if info.source_text is not None and (
        not isinstance(info.source_text, str)
        or len(info.source_text) > MAX_DEBUG_SOURCE_CHARS
    ):
        raise BytecodeFormatError("Embedded debug source is invalid or exceeds the size limit.")
    if not isinstance(info.local_symbols, tuple):
        raise BytecodeFormatError("Debug local-symbol table must be an immutable tuple.")
    chunks: list[dict[str, object]] = []
    seen_chunks: set[str] = set()
    for chunk_name, symbols in info.local_symbols:
        if (
            not isinstance(chunk_name, str) or not chunk_name
            or chunk_name in seen_chunks or not isinstance(symbols, tuple)
        ):
            raise BytecodeFormatError("Malformed or duplicate debug chunk metadata.")
        seen_chunks.add(chunk_name)
        locals_payload: list[dict[str, object]] = []
        seen_slots: set[int] = set()
        for symbol in symbols:
            if not isinstance(symbol, BytecodeDebugLocal):
                raise BytecodeFormatError("Malformed debug local-symbol entry.")
            if (
                type(symbol.slot) is not int or symbol.slot < 0
                or symbol.slot in seen_slots
                or not isinstance(symbol.name, str) or not symbol.name
                or not isinstance(symbol.type_name, str)
                or not _valid_debug_type_name(symbol.type_name, allow_nominal=allow_nominal)
            ):
                raise BytecodeFormatError("Invalid or duplicate debug local-symbol entry.")
            seen_slots.add(symbol.slot)
            locals_payload.append({
                "slot": symbol.slot,
                "name": symbol.name,
                "type": symbol.type_name,
            })
        chunks.append({"chunk": chunk_name, "locals": locals_payload})
    return {"source_text": info.source_text, "local_symbols": chunks}


def _debug_info_from_json(
    raw: object,
    *,
    allow_nominal: bool = False,
) -> BytecodeDebugInfo | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"source_text", "local_symbols"}:
        raise BytecodeFormatError("Malformed embedded debug metadata.")
    source_text = raw["source_text"]
    if source_text is not None and (
        not isinstance(source_text, str)
        or len(source_text) > MAX_DEBUG_SOURCE_CHARS
    ):
        raise BytecodeFormatError("Embedded debug source is invalid or exceeds the size limit.")
    raw_chunks = raw["local_symbols"]
    if not isinstance(raw_chunks, list):
        raise BytecodeFormatError("Debug local-symbol table must be an array.")
    chunks: list[tuple[str, tuple[BytecodeDebugLocal, ...]]] = []
    for chunk in raw_chunks:
        if not isinstance(chunk, dict) or set(chunk) != {"chunk", "locals"}:
            raise BytecodeFormatError("Malformed debug chunk metadata.")
        chunk_name, raw_locals = chunk["chunk"], chunk["locals"]
        if not isinstance(chunk_name, str) or not isinstance(raw_locals, list):
            raise BytecodeFormatError("Malformed debug chunk metadata.")
        symbols: list[BytecodeDebugLocal] = []
        for item in raw_locals:
            if not isinstance(item, dict) or set(item) != {"slot", "name", "type"}:
                raise BytecodeFormatError("Malformed debug local-symbol entry.")
            slot, name, type_name = item["slot"], item["name"], item["type"]
            if (
                type(slot) is not int
                or not isinstance(name, str)
                or not isinstance(type_name, str)
                or not _valid_debug_type_name(type_name, allow_nominal=allow_nominal)
            ):
                raise BytecodeFormatError("Debug local-symbol fields have invalid types.")
            symbols.append(BytecodeDebugLocal(slot, name, type_name))
        chunks.append((chunk_name, tuple(symbols)))
    return BytecodeDebugInfo(source_text, tuple(chunks))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BytecodeFormatError(f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


class BytecodeSerializer:
    """Encode and decode bytecode versions 1 through 5.

    Version 1 stores a main chunk, version 2 adds function chunks, version 3
    adds optional embedded debug metadata, version 4 adds typed arrays, and
    version 5 adds nominal struct/enum operations, and version 6 adds algebraic enum payloads. Older versions remain readable.
    """

    @staticmethod
    def to_bytes(module: BytecodeModule) -> bytes:
        if not isinstance(module, BytecodeModule):
            raise TypeError("module must be a BytecodeModule.")
        if type(module.format_version) is not int or module.format_version not in (
            LEGACY_FORMAT_VERSION, FUNCTIONS_FORMAT_VERSION,
            DEBUG_INFO_FORMAT_VERSION, COLLECTIONS_FORMAT_VERSION,
            NOMINAL_TYPES_FORMAT_VERSION,
            ALGEBRAIC_TYPES_FORMAT_VERSION,
            GENERIC_TYPES_FORMAT_VERSION,
        ):
            raise BytecodeFormatError(
                f"Cannot write bytecode version {module.format_version}; "
                "supported versions are 1 through 7."
            )
        if module.format_version < FUNCTIONS_FORMAT_VERSION and module.functions:
            raise BytecodeFormatError("Version 1 bytecode cannot contain function chunks.")
        if module.format_version < DEBUG_INFO_FORMAT_VERSION and module.debug_info is not None:
            raise BytecodeFormatError("Embedded debug metadata requires bytecode version 3.")
        if any(not is_constant(value) for value in module.constants):
            raise BytecodeFormatError("Module contains an unsupported constant.")

        try:
            payload: dict[str, object] = {
                "magic": "RIFAI",
                "format_version": module.format_version,
                "source_name": module.source_name,
                "constants": [_constant_to_json(value) for value in module.constants],
                "main": _chunk_to_json(module.main),
            }
            if module.format_version >= FUNCTIONS_FORMAT_VERSION:
                payload["functions"] = [
                    _function_to_json(function) for function in module.functions
                ]
            if module.format_version >= DEBUG_INFO_FORMAT_VERSION:
                payload["debug_info"] = _debug_info_to_json(
                    module.debug_info,
                    allow_nominal=module.format_version >= NOMINAL_TYPES_FORMAT_VERSION,
                )
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
        except BytecodeFormatError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise BytecodeFormatError(f"Invalid bytecode payload: {exc}") from exc

        if not isinstance(payload, dict):
            raise BytecodeFormatError("Bytecode module has an invalid top-level structure.")
        version = payload.get("format_version")
        if type(version) is not int or version not in (
            LEGACY_FORMAT_VERSION, FUNCTIONS_FORMAT_VERSION,
            DEBUG_INFO_FORMAT_VERSION, COLLECTIONS_FORMAT_VERSION,
            NOMINAL_TYPES_FORMAT_VERSION,
            ALGEBRAIC_TYPES_FORMAT_VERSION,
            GENERIC_TYPES_FORMAT_VERSION,
        ):
            raise BytecodeFormatError(
                f"Unsupported bytecode version {version!r}; supported versions are 1 through 7."
            )

        expected_fields = {"magic", "format_version", "source_name", "constants", "main"}
        if version >= FUNCTIONS_FORMAT_VERSION:
            expected_fields.add("functions")
        if version >= DEBUG_INFO_FORMAT_VERSION:
            expected_fields.add("debug_info")
        if set(payload) != expected_fields:
            raise BytecodeFormatError("Bytecode module has an invalid top-level structure.")
        if payload["magic"] != "RIFAI":
            raise BytecodeFormatError("Bytecode magic identifier does not match.")
        source_name = payload["source_name"]
        if source_name is not None and not isinstance(source_name, str):
            raise BytecodeFormatError("source_name must be a string or null.")
        raw_constants = payload["constants"]
        if not isinstance(raw_constants, list):
            raise BytecodeFormatError("Constant pool must be an array.")
        constants = tuple(_constant_from_json(item) for item in raw_constants)
        main = _chunk_from_json(payload["main"])

        raw_functions = payload.get("functions", [])
        if not isinstance(raw_functions, list):
            raise BytecodeFormatError("Function table must be an array.")
        functions = tuple(_function_from_json(item) for item in raw_functions)
        debug_info = _debug_info_from_json(
                payload.get("debug_info"),
                allow_nominal=version >= NOMINAL_TYPES_FORMAT_VERSION,
            )
        return BytecodeModule(
            constants=constants,
            main=main,
            source_name=source_name,
            format_version=version,
            functions=functions,
            debug_info=debug_info,
        )

    @classmethod
    def write(cls, module: BytecodeModule, path: str | Path) -> None:
        """Write a complete bytecode file atomically in the destination directory."""
        data = cls.to_bytes(module)
        target = Path(path)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @classmethod
    def read(cls, path: str | Path) -> BytecodeModule:
        """Read at most the format limit plus one byte before rejecting oversized files."""
        target = Path(path)
        with target.open("rb") as stream:
            data = stream.read(MAX_BYTECODE_SIZE + 1)
        if len(data) > MAX_BYTECODE_SIZE:
            raise BytecodeFormatError("Bytecode module exceeds the maximum file size.")
        return cls.from_bytes(data)
