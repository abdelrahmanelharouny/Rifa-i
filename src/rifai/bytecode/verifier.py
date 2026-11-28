"""Structural and control-flow verification for Rifa'i bytecode."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import (
    Instruction,
    Opcode,
    SourceLocation,
    expected_operand_kind,
    stack_delta,
    stack_requirement,
)
from rifai.bytecode.module import (
    BytecodeDebugInfo,
    BytecodeDebugLocal,
    BytecodeModule,
    COLLECTIONS_FORMAT_VERSION,
    NOMINAL_TYPES_FORMAT_VERSION,
    ALGEBRAIC_TYPES_FORMAT_VERSION,
    DEBUG_INFO_FORMAT_VERSION,
    FORMAT_VERSION,
    FUNCTIONS_FORMAT_VERSION,
    LEGACY_FORMAT_VERSION,
    is_constant,
)
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.stdlib import BUILTIN_ARITIES, BUILTIN_FUNCTIONS

_ALLOWED_VALUE_TYPES = frozenset({"int", "float", "bool", "string", "int[]", "float[]", "bool[]", "string[]"})
_ALLOWED_RETURN_TYPES = _ALLOWED_VALUE_TYPES | {"void"}
MAX_CONSTANT_COUNT = 500_000
MAX_FUNCTION_COUNT = 100_000
MAX_INSTRUCTIONS_PER_CHUNK = 1_000_000
MAX_LOCAL_COUNT = 100_000
MAX_CONSTANT_STRING_CHARS = 16 * 1024 * 1024
MAX_DEBUG_SOURCE_CHARS = 8 * 1024 * 1024


def _is_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value))


def _is_nominal_type_name(value: str) -> bool:
    return (
        _is_identifier(value)
        and value != "void"
        and value not in BUILTIN_FUNCTIONS
        and value not in _ALLOWED_VALUE_TYPES
    )


def _valid_type_name(value: str, allow_nominal: bool) -> bool:
    return value in _ALLOWED_VALUE_TYPES or (allow_nominal and _is_nominal_type_name(value))


def _valid_struct_schema(value: str) -> bool:
    if len(value) > 4096 or "|" not in value:
        return False
    type_name, fields = value.split("|", 1)
    if not _is_nominal_type_name(type_name) or not fields:
        return False
    seen: set[str] = set()
    for field in fields.split(","):
        if ":" not in field:
            return False
        name, field_type = field.split(":", 1)
        if not _is_identifier(name) or name in seen:
            return False
        if field_type not in _ALLOWED_VALUE_TYPES and not _is_nominal_type_name(field_type):
            return False
        seen.add(name)
    return bool(seen)


def _valid_enum_variant(value: str) -> bool:
    if len(value) > 4096 or value.count("|") != 2:
        return False
    type_name, variants_text, active = value.split("|")
    if not _is_nominal_type_name(type_name) or not _is_identifier(active):
        return False
    variants = variants_text.split(",") if variants_text else []
    return (
        0 < len(variants) <= 256
        and all(_is_identifier(item) for item in variants)
        and len(set(variants)) == len(variants)
        and active in variants
    )


def _valid_enum_payload_schema(value: str) -> bool:
    if len(value) > 4096 or value.count("|") != 2:
        return False
    enum_name, variant, payload_text = value.split("|", 2)
    if not _is_nominal_type_name(enum_name) or not _is_identifier(variant):
        return False
    payload_types = payload_text.split(",") if payload_text else []
    return len(payload_types) <= 256 and all(
        item in _ALLOWED_VALUE_TYPES or _is_nominal_type_name(item)
        for item in payload_types
    )


def _valid_enum_test(value: str) -> bool:
    return (
        len(value) <= 512
        and value.count("|") == 1
        and all(_is_identifier(item) for item in value.split("|"))
        and _is_nominal_type_name(value.split("|", 1)[0])
    )


def _valid_enum_payload_access(value: str) -> bool:
    if len(value) > 1024 or value.count("|") != 3:
        return False
    enum_name, variant, index_text, expected = value.split("|", 3)
    return (
        _is_nominal_type_name(enum_name)
        and _is_identifier(variant)
        and index_text.isdigit()
        and int(index_text) <= 255
        and (expected in _ALLOWED_VALUE_TYPES or _is_nominal_type_name(expected))
    )


@dataclass(frozen=True, slots=True)
class BytecodeValidationResult:
    """Result of validating a bytecode module."""

    diagnostics: tuple[Diagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


class BytecodeVerifier:
    """Validate module structure and operand-stack data flow before execution."""

    def verify(self, module: BytecodeModule) -> BytecodeValidationResult:
        diagnostics: list[Diagnostic] = []

        def report(message: str, instruction: Instruction | None = None) -> None:
            location = (
                instruction.location
                if isinstance(instruction, Instruction)
                and isinstance(instruction.location, SourceLocation)
                else None
            )
            diagnostics.append(
                Diagnostic(
                    phase=DiagnosticPhase.BYTECODE,
                    message=message,
                    line=location.line if location else 1,
                    column=location.column if location else 1,
                    start_offset=location.start_offset if location else None,
                    end_offset=location.end_offset if location else None,
                )
            )

        if not isinstance(module, BytecodeModule):
            report("Expected a BytecodeModule instance.")
            return BytecodeValidationResult(tuple(diagnostics))
        if type(module.format_version) is not int or module.format_version not in (
            LEGACY_FORMAT_VERSION,
            FUNCTIONS_FORMAT_VERSION,
            DEBUG_INFO_FORMAT_VERSION,
            COLLECTIONS_FORMAT_VERSION,
            NOMINAL_TYPES_FORMAT_VERSION,
            ALGEBRAIC_TYPES_FORMAT_VERSION,
        ):
            report(f"Unsupported bytecode version {module.format_version!r}.")
        if module.source_name is not None and not isinstance(module.source_name, str):
            report("Module source_name must be a string or null.")
        if not isinstance(module.constants, tuple):
            report("Module constants must be an immutable tuple.")
        else:
            if len(module.constants) > MAX_CONSTANT_COUNT:
                report(f"Constant pool exceeds the limit ({MAX_CONSTANT_COUNT}).")
                return BytecodeValidationResult(tuple(diagnostics))
            for index, value in enumerate(module.constants):
                if not is_constant(value):
                    report(f"Constant pool entry {index} has an unsupported value.")
                elif type(value) is str and len(value) > MAX_CONSTANT_STRING_CHARS:
                    report(
                        f"Constant pool string {index} exceeds the size limit "
                        f"({MAX_CONSTANT_STRING_CHARS} characters)."
                    )

        if not isinstance(module.main, CodeChunk):
            report("Module main must be a CodeChunk.")
            return BytecodeValidationResult(tuple(diagnostics))
        if not isinstance(module.functions, tuple):
            report("Module functions must be an immutable tuple.")
            return BytecodeValidationResult(tuple(diagnostics))
        if len(module.functions) > MAX_FUNCTION_COUNT:
            report(f"Function table exceeds the limit ({MAX_FUNCTION_COUNT}).")
            return BytecodeValidationResult(tuple(diagnostics))
        supports_functions = (
            type(module.format_version) is int
            and module.format_version >= FUNCTIONS_FORMAT_VERSION
        )
        supports_debug_info = (
            type(module.format_version) is int
            and module.format_version >= DEBUG_INFO_FORMAT_VERSION
        )
        supports_collections = (
            type(module.format_version) is int
            and module.format_version >= COLLECTIONS_FORMAT_VERSION
        )
        supports_nominal_types = (
            type(module.format_version) is int
            and module.format_version >= NOMINAL_TYPES_FORMAT_VERSION
        )
        supports_algebraic_types = (
            type(module.format_version) is int
            and module.format_version >= ALGEBRAIC_TYPES_FORMAT_VERSION
        )
        if not supports_functions and module.functions:
            report("Version 1 bytecode cannot contain function chunks.")
        if not supports_debug_info and module.debug_info is not None:
            report("Embedded debug metadata requires bytecode version 3.")
        if module.debug_info is not None:
            info = module.debug_info
            if not isinstance(info, BytecodeDebugInfo):
                report("Module debug_info has an invalid type.")
            else:
                if info.source_text is not None:
                    if not isinstance(info.source_text, str):
                        report("Embedded debug source must be a string or null.")
                    elif len(info.source_text) > MAX_DEBUG_SOURCE_CHARS:
                        report("Embedded debug source exceeds the size limit.")
                chunk_limits: dict[str, int | None] = {
                    "<main>": (
                        module.main.local_count
                        if type(module.main.local_count) is int
                        else None
                    )
                }
                for item in module.functions:
                    if isinstance(item, BytecodeFunction) and isinstance(item.chunk, CodeChunk):
                        chunk_limits[item.name] = (
                            item.chunk.local_count
                            if type(item.chunk.local_count) is int
                            else None
                        )
                if not isinstance(info.local_symbols, tuple):
                    report("Debug local-symbol table must be an immutable tuple.")
                else:
                    seen_chunks: set[str] = set()
                    for entry in info.local_symbols:
                        if not isinstance(entry, tuple) or len(entry) != 2:
                            report("Debug chunk metadata entry is malformed.")
                            continue
                        chunk_name, symbols = entry
                        if not isinstance(chunk_name, str) or chunk_name not in chunk_limits:
                            report("Debug metadata references an unknown code chunk.")
                            continue
                        if chunk_name in seen_chunks:
                            report(f"Duplicate debug metadata for chunk '{chunk_name}'.")
                            continue
                        seen_chunks.add(chunk_name)
                        if not isinstance(symbols, tuple):
                            report(f"Debug symbols for '{chunk_name}' must be an immutable tuple.")
                            continue
                        seen_slots: set[int] = set()
                        for symbol in symbols:
                            if not isinstance(symbol, BytecodeDebugLocal):
                                report(f"Debug metadata for '{chunk_name}' contains an invalid local.")
                                continue
                            chunk_size = chunk_limits[chunk_name]
                            if (
                                type(symbol.slot) is not int
                                or symbol.slot < 0
                                or chunk_size is None
                                or symbol.slot >= chunk_size
                            ):
                                report(f"Debug local slot in '{chunk_name}' is out of range.")
                            elif symbol.slot in seen_slots:
                                report(f"Duplicate debug local slot {symbol.slot} in '{chunk_name}'.")
                            else:
                                seen_slots.add(symbol.slot)
                            if not isinstance(symbol.name, str) or not symbol.name:
                                report(f"Debug local in '{chunk_name}' has an invalid name.")
                            if not isinstance(symbol.type_name, str) or not _valid_type_name(symbol.type_name, supports_nominal_types):
                                report(f"Debug local in '{chunk_name}' has an invalid type.")
                            elif not supports_collections and symbol.type_name.endswith("[]"):
                                report(
                                    f"Array debug local types require bytecode version "
                                    f"{COLLECTIONS_FORMAT_VERSION}."
                                )

        function_by_name: dict[str, BytecodeFunction] = {}
        seen_function_names: set[str] = set()
        for function in module.functions:
            if not isinstance(function, BytecodeFunction):
                report("Function table contains an invalid entry.")
                continue
            if not isinstance(function.name, str) or not function.name:
                report("Function names must be non-empty strings.")
                continue
            if function.name in seen_function_names:
                report(f"Duplicate function '{function.name}' in bytecode module.")
                continue
            seen_function_names.add(function.name)
            if not isinstance(function.chunk, CodeChunk):
                report(f"Function '{function.name}' has an invalid code chunk.")
                continue
            if function.chunk.name != function.name:
                report(f"Function '{function.name}' chunk name does not match its metadata.")
            parameter_types_valid = (
                isinstance(function.parameter_types, tuple)
                and all(
                    isinstance(item, str) and _valid_type_name(item, supports_nominal_types)
                    for item in function.parameter_types
                )
            )
            if not parameter_types_valid:
                report(f"Function '{function.name}' has invalid parameter types.")
            return_type_valid = (
                isinstance(function.return_type, str)
                and (function.return_type in _ALLOWED_RETURN_TYPES or (
                    supports_nominal_types and _is_nominal_type_name(function.return_type)
                ))
            )
            if not return_type_valid:
                report(f"Function '{function.name}' has an invalid return type.")
            if not supports_collections and parameter_types_valid and any(
                item.endswith("[]") for item in function.parameter_types
            ):
                report(
                    f"Function '{function.name}' array parameters require bytecode version "
                    f"{COLLECTIONS_FORMAT_VERSION}."
                )
            if (
                not supports_collections
                and return_type_valid
                and function.return_type.endswith("[]")
            ):
                report(
                    f"Function '{function.name}' array return type requires bytecode version "
                    f"{COLLECTIONS_FORMAT_VERSION}."
                )
            if (
                parameter_types_valid
                and function.chunk.arity != len(function.parameter_types)
            ):
                report(f"Function '{function.name}' arity does not match its signature.")
            # Only well-formed signatures are valid CALL targets. This prevents
            # malformed metadata from crashing call-stack verification below.
            if parameter_types_valid and return_type_valid:
                function_by_name[function.name] = function

        chunks: list[tuple[str, CodeChunk, str | None, bool]] = [
            ("<main>", module.main, None, True)
        ]
        for function in module.functions:
            if isinstance(function, BytecodeFunction) and isinstance(function.chunk, CodeChunk):
                chunks.append((function.name, function.chunk, function.return_type, False))

        for chunk_name, chunk, return_type, is_main in chunks:
            if not isinstance(chunk.name, str) or not chunk.name:
                report(f"Code chunk '{chunk_name}' must have a non-empty name.")
            if type(chunk.arity) is not int or chunk.arity < 0:
                report(f"Code chunk '{chunk_name}' arity must be non-negative.")
            if type(chunk.local_count) is not int or chunk.local_count < 0:
                report(f"Code chunk '{chunk_name}' local_count must be non-negative.")
            elif chunk.local_count > MAX_LOCAL_COUNT:
                report(
                    f"Code chunk '{chunk_name}' local_count exceeds the limit "
                    f"({MAX_LOCAL_COUNT})."
                )
            elif type(chunk.arity) is int and chunk.arity > chunk.local_count:
                report(f"Code chunk '{chunk_name}' arity cannot exceed local_count.")

            instructions = chunk.instructions
            if not isinstance(instructions, tuple):
                report(f"Code chunk '{chunk_name}' instructions must be a tuple.")
                continue
            if len(instructions) > MAX_INSTRUCTIONS_PER_CHUNK:
                report(
                    f"Code chunk '{chunk_name}' exceeds the instruction limit "
                    f"({MAX_INSTRUCTIONS_PER_CHUNK})."
                )
                continue
            if not instructions:
                report(f"Code chunk '{chunk_name}' is empty.")
                continue

            if is_main:
                if (
                    not isinstance(instructions[-1], Instruction)
                    or instructions[-1].opcode is not Opcode.HALT
                ):
                    report("The main chunk must end with HALT.")
                halt_positions = [
                    index for index, item in enumerate(instructions)
                    if isinstance(item, Instruction) and item.opcode is Opcode.HALT
                ]
                if len(halt_positions) != 1 or (
                    halt_positions and halt_positions[0] != len(instructions) - 1
                ):
                    report("The main chunk must contain exactly one final HALT.")
            elif not any(
                isinstance(item, Instruction) and item.opcode is Opcode.RETURN
                for item in instructions
            ):
                report(f"Function '{chunk_name}' has no RETURN instruction.")

            structurally_valid: set[int] = set()
            for index, instruction in enumerate(instructions):
                if not isinstance(instruction, Instruction):
                    report(f"Instruction {index} in '{chunk_name}' is invalid.")
                    continue
                if not isinstance(instruction.opcode, Opcode):
                    report(f"Instruction {index} in '{chunk_name}' has an unknown opcode.")
                    continue

                location = instruction.location
                if location is not None:
                    if not isinstance(location, SourceLocation):
                        report(
                            f"Instruction {index} in '{chunk_name}' has an invalid source location.",
                            instruction,
                        )
                        continue
                    coordinates = (
                        location.line,
                        location.column,
                        location.start_offset,
                        location.end_offset,
                    )
                    if (
                        any(type(value) is not int for value in coordinates)
                        or location.line < 1
                        or location.column < 1
                        or location.start_offset < 0
                        or location.end_offset < location.start_offset
                    ):
                        report(
                            f"Instruction {index} in '{chunk_name}' has invalid source coordinates.",
                            instruction,
                        )
                        continue

                opcode = instruction.opcode
                kind = expected_operand_kind(opcode)
                operand = instruction.operand
                if kind == "integer" and type(operand) is not int:
                    report(f"{opcode.value} at instruction {index} requires an integer operand.", instruction)
                    continue
                if kind == "string" and (
                    not isinstance(operand, str) or not operand
                ):
                    report(f"{opcode.value} at instruction {index} requires a non-empty string operand.", instruction)
                    continue
                if kind == "none" and operand is not None:
                    report(f"{opcode.value} at instruction {index} does not accept an operand.", instruction)
                    continue

                if opcode is Opcode.CONSTANT:
                    if not isinstance(module.constants, tuple) or not 0 <= operand < len(module.constants):
                        report(f"Constant index {operand} is out of range at instruction {index}.", instruction)
                        continue
                elif opcode in (Opcode.LOAD_LOCAL, Opcode.STORE_LOCAL):
                    if type(chunk.local_count) is not int or not 0 <= operand < chunk.local_count:
                        report(f"Local slot {operand} is out of range at instruction {index}.", instruction)
                        continue
                elif opcode in (Opcode.JUMP, Opcode.JUMP_IF_FALSE):
                    if not 0 <= operand < len(instructions):
                        report(f"Jump target {operand} is out of range at instruction {index}.", instruction)
                        continue
                elif opcode in {
                    Opcode.ARRAY_NEW_INT, Opcode.ARRAY_NEW_FLOAT,
                    Opcode.ARRAY_NEW_BOOL, Opcode.ARRAY_NEW_STRING,
                    Opcode.ARRAY_GET, Opcode.ARRAY_SET, Opcode.LENGTH,
                    Opcode.ARRAY_PUSH, Opcode.ARRAY_POP,
                } and not supports_collections:
                    report(
                        f"{opcode.value} requires bytecode version {COLLECTIONS_FORMAT_VERSION}.",
                        instruction,
                    )
                    continue
                elif opcode in {
                    Opcode.ARRAY_NEW_INT, Opcode.ARRAY_NEW_FLOAT,
                    Opcode.ARRAY_NEW_BOOL, Opcode.ARRAY_NEW_STRING,
                } and (operand < 0 or operand > 1_000_000):
                    report("Array literal element count is outside the supported limit.", instruction)
                    continue
                elif opcode in {Opcode.STRUCT_NEW, Opcode.FIELD_GET, Opcode.FIELD_SET, Opcode.ENUM_NEW}:
                    if not supports_nominal_types:
                        report(f"{opcode.value} requires bytecode version {NOMINAL_TYPES_FORMAT_VERSION}.", instruction)
                        continue
                    if not isinstance(operand, str) or not operand:
                        report(f"{opcode.value} requires a non-empty string operand.", instruction)
                        continue
                    if opcode is Opcode.STRUCT_NEW and not _valid_struct_schema(operand):
                        report("STRUCT_NEW has an invalid or oversized field schema.", instruction)
                        continue
                    if opcode in (Opcode.FIELD_GET, Opcode.FIELD_SET) and not _is_identifier(operand):
                        report(f"{opcode.value} has an invalid field name.", instruction)
                        continue
                    if opcode is Opcode.ENUM_NEW and not _valid_enum_variant(operand):
                        report("ENUM_NEW requires a valid Enum|Variants|SelectedVariant schema.", instruction)
                        continue
                elif opcode in {Opcode.ENUM_NEW_PAYLOAD, Opcode.ENUM_IS, Opcode.ENUM_GET}:
                    if not supports_algebraic_types:
                        report(f"{opcode.value} requires bytecode version {ALGEBRAIC_TYPES_FORMAT_VERSION}.", instruction)
                        continue
                    if not isinstance(operand, str) or not operand:
                        report(f"{opcode.value} requires a non-empty string operand.", instruction)
                        continue
                    valid = (
                        _valid_enum_payload_schema(operand) if opcode is Opcode.ENUM_NEW_PAYLOAD
                        else _valid_enum_test(operand) if opcode is Opcode.ENUM_IS
                        else _valid_enum_payload_access(operand)
                    )
                    if not valid:
                        report(f"{opcode.value} has an invalid enum payload or pattern operand.", instruction)
                        continue
                elif opcode is Opcode.CALL:
                    if operand in BUILTIN_ARITIES and not supports_nominal_types:
                        report(
                            f"Standard-library CALL '{operand}' requires bytecode version {NOMINAL_TYPES_FORMAT_VERSION}.",
                            instruction,
                        )
                        continue
                    if not supports_functions or (
                        operand not in function_by_name and operand not in BUILTIN_ARITIES
                    ):
                        report(f"Call target '{operand}' does not exist in this bytecode module or standard library.", instruction)
                        continue
                elif opcode is Opcode.HALT and not is_main:
                    report("HALT is only valid in the main chunk.", instruction)
                    continue
                elif opcode is Opcode.RETURN and is_main:
                    report("RETURN is only valid inside a function chunk.", instruction)
                    continue
                structurally_valid.add(index)

            if 0 not in structurally_valid:
                continue

            depths: dict[int, int] = {0: 0}
            queue: deque[int] = deque([0])
            while queue:
                index = queue.popleft()
                if index not in structurally_valid:
                    continue
                instruction = instructions[index]
                opcode = instruction.opcode
                before = depths[index]

                if opcode is Opcode.ENUM_NEW_PAYLOAD:
                    payload_text = instruction.operand.split("|", 2)[2]
                    payload_types = payload_text.split(",") if payload_text else []
                    required = len(payload_types)
                    delta = 1 - required
                elif opcode is Opcode.ENUM_IS or opcode is Opcode.ENUM_GET:
                    required = 1
                    delta = 0
                elif opcode is Opcode.CALL:
                    target = function_by_name.get(instruction.operand)
                    required = target.arity if target is not None else BUILTIN_ARITIES.get(instruction.operand, 0)
                    returns_value = target.returns_value if target is not None else True
                    delta = -required + (1 if returns_value else 0)
                elif opcode in {
                    Opcode.ARRAY_NEW_INT, Opcode.ARRAY_NEW_FLOAT,
                    Opcode.ARRAY_NEW_BOOL, Opcode.ARRAY_NEW_STRING,
                }:
                    required = instruction.operand
                    delta = 1 - instruction.operand
                elif opcode is Opcode.RETURN:
                    required = 1 if return_type != "void" else 0
                    delta = 0
                else:
                    required = stack_requirement(opcode)
                    delta = stack_delta(opcode)

                if before < required:
                    report(
                        f"Stack underflow in '{chunk_name}' at instruction {index} "
                        f"({opcode.value}): requires {required}, has {before}.",
                        instruction,
                    )
                    continue

                if opcode is Opcode.RETURN:
                    expected_depth = 1 if return_type != "void" else 0
                    if before != expected_depth:
                        report(
                            f"RETURN in '{chunk_name}' requires stack depth {expected_depth}, "
                            f"found {before}.",
                            instruction,
                        )
                    successors: tuple[int, ...] = ()
                elif opcode is Opcode.HALT:
                    if before != 0:
                        report(f"Stack must be empty at HALT; found depth {before}.", instruction)
                    successors = ()
                elif opcode is Opcode.JUMP:
                    successors = (instruction.operand,)
                elif opcode is Opcode.JUMP_IF_FALSE:
                    successors = (instruction.operand, index + 1)
                else:
                    successors = (index + 1,)

                after = before + delta
                for successor in successors:
                    if successor >= len(instructions):
                        report(f"Execution can fall off the end of '{chunk_name}' after instruction {index}.", instruction)
                        continue
                    if successor not in structurally_valid:
                        continue
                    known = depths.get(successor)
                    if known is None:
                        depths[successor] = after
                        queue.append(successor)
                    elif known != after:
                        report(
                            f"Inconsistent stack depth at control-flow merge in '{chunk_name}' "
                            f"instruction {successor}: {known} versus {after}.",
                            instructions[successor],
                        )

        return BytecodeValidationResult(tuple(diagnostics))
