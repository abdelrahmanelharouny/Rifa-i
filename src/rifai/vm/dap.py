"""Debug Adapter Protocol server for the Rifa'i VM.

The adapter uses DAP's Content-Length framed stdio transport. VM execution runs
on a worker thread so the protocol loop remains responsive while execution is
paused at entry, source breakpoints, or step boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import re
import sys
from threading import Condition, Lock, Thread
from typing import Any, BinaryIO

from rifai.bytecode.serializer import BytecodeFormatError, BytecodeSerializer
from rifai.bytecode.verifier import BytecodeVerifier
from rifai.compiler import Compiler
from rifai.vm.machine import InstructionSnapshot, VirtualMachine
from rifai.vm.runtime import BytecodeValidationError, VMRuntimeError, format_value

MAX_DAP_MESSAGE_SIZE = 8 * 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DAPProtocolError(ValueError):
    """Raised when a DAP message is malformed or exceeds protocol limits."""


class _AbortDebugSession(Exception):
    """Internal signal used to stop a VM worker after terminate/disconnect."""


class RifaIDebugAdapter:
    """A small DAP adapter exposing Rifa'i breakpoints, stepping and inspection."""

    def __init__(
        self,
        reader: BinaryIO | None = None,
        writer: BinaryIO | None = None,
    ) -> None:
        self.reader = reader if reader is not None else sys.stdin.buffer
        self.writer = writer if writer is not None else sys.stdout.buffer
        self._write_lock = Lock()
        self._condition = Condition()
        self._sequence = 1
        self._module = None
        self._program_path: Path | None = None
        self._source_path: Path | None = None
        self._source_name = "<unknown>"
        self._source_text = ""
        self._source_reference = 0
        self._debug_symbols: dict[str, dict[int, tuple[str, str]]] = {}
        self._available_lines: set[int] = set()
        self._breakpoints: set[int] = set()
        self._breakpoint_ids: dict[int, int] = {}
        self._next_breakpoint_id = 1
        self._stop_on_entry = True
        self._first_instruction = True
        self._mode = "continue"
        self._origin: InstructionSnapshot | None = None
        self._breakpoint_suppression: tuple[tuple[str, ...], int] | None = None
        self._pause_requested = False
        self._resume_requested = False
        self._resume_mode = "continue"
        self._terminated = False
        self._disconnected = False
        self._worker_finished = False
        self._paused_snapshot: InstructionSnapshot | None = None
        self._frame_ids: dict[int, int] = {}
        self._variable_references: dict[int, tuple[str, int]] = {}
        self._next_variable_reference = 1
        self._worker: Thread | None = None
        self._execution_error: str | None = None
        self._initialized = False

    def _write_locked(self, message: dict[str, Any]) -> None:
        payload = json.dumps(
            message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(payload) > MAX_DAP_MESSAGE_SIZE:
            raise DAPProtocolError("Outgoing DAP message exceeds the size limit.")
        frame = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        self.writer.write(frame)
        self.writer.flush()

    def _send(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            self._write_locked(message)

    def _response(
        self,
        request: Mapping[str, Any],
        body: dict[str, Any] | None = None,
        *,
        success: bool = True,
        message: str | None = None,
    ) -> None:
        with self._write_lock:
            response: dict[str, Any] = {
                "seq": self._sequence,
                "type": "response",
                "request_seq": request.get("seq", 0),
                "success": success,
                "command": request.get("command", ""),
                "body": body or {},
            }
            self._sequence += 1
            if message is not None:
                response["message"] = message
            self._write_locked(response)

    def _event(self, name: str, body: dict[str, Any] | None = None) -> None:
        with self._write_lock:
            event = {
                "seq": self._sequence,
                "type": "event",
                "event": name,
                "body": body or {},
            }
            self._sequence += 1
            self._write_locked(event)

    def _read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = self.reader.readline()
            if not line:
                if not headers:
                    return None
                raise DAPProtocolError("Unexpected EOF inside DAP headers.")
            if line in (b"\r\n", b"\n"):
                break
            try:
                decoded = line.decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise DAPProtocolError("DAP headers must be ASCII.") from exc
            name, separator, value = decoded.partition(":")
            if not separator:
                raise DAPProtocolError("Malformed DAP header.")
            headers[name.lower()] = value.strip()

        raw_length = headers.get("content-length")
        if raw_length is None or not raw_length.isdigit():
            raise DAPProtocolError("A valid Content-Length header is required.")
        length = int(raw_length)
        if length < 1 or length > MAX_DAP_MESSAGE_SIZE:
            raise DAPProtocolError("DAP message length is outside the supported limit.")
        payload = self.reader.read(length)
        if len(payload) != length:
            raise DAPProtocolError("Unexpected EOF inside DAP message body.")
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DAPProtocolError(f"Invalid DAP JSON payload: {exc}") from exc
        if not isinstance(message, dict) or message.get("type") != "request":
            raise DAPProtocolError("Expected a DAP request object.")
        if not isinstance(message.get("command"), str):
            raise DAPProtocolError("DAP request command must be a string.")
        return message

    @staticmethod
    def _arguments(request: Mapping[str, Any]) -> dict[str, Any]:
        args = request.get("arguments", {})
        if not isinstance(args, dict):
            raise DAPProtocolError("DAP request arguments must be an object.")
        return args

    def _load_program(self, arguments: dict[str, Any]) -> None:
        raw_program = arguments.get("program")
        if not isinstance(raw_program, str) or not raw_program.strip():
            raise ValueError("Launch configuration must contain a non-empty 'program' path.")
        path = Path(raw_program).expanduser()
        if not path.is_file():
            raise ValueError(f"Program file does not exist: {path}")
        self._program_path = path.resolve()

        suffix = path.suffix.lower()
        if suffix == ".rif":
            source = path.read_text(encoding="utf-8")
            compilation = Compiler(
                optimize=not bool(arguments.get("noOptimize", False))
            ).compile(source, source_name=str(self._program_path))
            if not compilation.is_success or compilation.module is None:
                detail = "\n".join(item.format(str(self._program_path)) for item in compilation.diagnostics)
                raise ValueError(detail or "Rifa'i source compilation failed.")
            module = compilation.module
        elif suffix == ".rbc":
            module = BytecodeSerializer.read(path)
        else:
            raise ValueError("The 'program' path must point to a .rif or .rbc file.")

        validation = BytecodeVerifier().verify(module)
        if not validation.is_valid:
            raise ValueError(
                "Bytecode verification failed:\n"
                + "\n".join(item.format(str(path)) for item in validation.diagnostics)
            )

        info = module.debug_info
        embedded_source = info.source_text if info is not None else None
        source_path: Path | None = None
        if suffix == ".rif":
            source_path = self._program_path
        elif module.source_name:
            candidate = Path(module.source_name).expanduser()
            if not candidate.is_absolute() and not candidate.is_file():
                candidate = (path.parent / candidate).resolve()
            if candidate.is_file():
                source_path = candidate

        if embedded_source is not None:
            source_text = embedded_source
        elif source_path is not None:
            source_text = source_path.read_text(encoding="utf-8")
        else:
            source_text = ""

        self._module = module
        self._source_path = source_path
        self._source_name = (
            str(source_path) if source_path is not None
            else (module.source_name or path.name)
        )
        self._source_text = source_text
        self._source_reference = 1 if source_text else 0
        self._debug_symbols = info.as_mapping() if info is not None else {}
        self._available_lines = {
            instruction.location.line
            for chunk in (module.main, *(item.chunk for item in module.functions))
            for instruction in chunk.instructions
            if instruction.location is not None
        }
        self._stop_on_entry = bool(arguments.get("stopOnEntry", True))
        self._first_instruction = True
        self._mode = "continue"
        self._origin = None
        self._breakpoint_suppression = None
        self._breakpoints.clear()
        self._breakpoint_ids.clear()
        self._next_breakpoint_id = 1
        self._terminated = False
        self._disconnected = False
        self._worker_finished = False
        self._paused_snapshot = None
        self._frame_ids.clear()
        self._variable_references.clear()
        self._execution_error = None

    def _source_object(self) -> dict[str, Any]:
        source: dict[str, Any] = {"name": Path(self._source_name).name or self._source_name}
        if self._source_path is not None:
            source["path"] = str(self._source_path)
        if self._source_reference:
            source["sourceReference"] = self._source_reference
        return source

    def _handle_set_breakpoints(self, request: Mapping[str, Any], args: dict[str, Any]) -> None:
        source = args.get("source", {})
        if not isinstance(source, dict):
            self._response(request, success=False, message="source must be an object")
            return
        requested = args.get("breakpoints", [])
        if not isinstance(requested, list):
            self._response(request, success=False, message="breakpoints must be an array")
            return

        verified: list[dict[str, Any]] = []
        selected: set[int] = set()
        for item in requested:
            if not isinstance(item, dict):
                continue
            line = item.get("line")
            if type(line) is not int or line < 1:
                verified.append({"verified": False, "message": "Line must be a positive integer."})
                continue
            if line not in self._available_lines:
                verified.append({
                    "verified": False,
                    "line": line,
                    "message": "No executable bytecode is mapped to this source line.",
                })
                continue
            breakpoint_id = self._breakpoint_ids.get(line)
            if breakpoint_id is None:
                breakpoint_id = self._next_breakpoint_id
                self._next_breakpoint_id += 1
                self._breakpoint_ids[line] = breakpoint_id
            selected.add(line)
            verified.append({"id": breakpoint_id, "verified": True, "line": line})

        with self._condition:
            self._breakpoints = selected
        self._response(request, {"breakpoints": verified})

    def _location_for_frame(
        self, snapshot: InstructionSnapshot, frame_index: int
    ) -> tuple[str, int, int]:
        frame = snapshot.frames[frame_index]
        if frame.is_main:
            chunk = self._module.main
        else:
            function = next(
                (item for item in self._module.functions if item.name == frame.name),
                None,
            )
            chunk = function.chunk if function is not None else self._module.main
        instruction_index = min(
            max(0, frame.instruction_pointer), len(chunk.instructions) - 1
        )
        location = (
            snapshot.instruction.location
            if frame_index == len(snapshot.frames) - 1
            else chunk.instructions[instruction_index].location
        )
        if location is None:
            return self._source_name, 1, 1
        return self._source_name, location.line, location.column

    def _handle_stack_trace(self, request: Mapping[str, Any], args: dict[str, Any]) -> None:
        snapshot = self._paused_snapshot
        if snapshot is None:
            self._response(request, {"stackFrames": [], "totalFrames": 0})
            return
        frames: list[dict[str, Any]] = []
        self._frame_ids.clear()
        newest_first = list(reversed(range(len(snapshot.frames))))
        for offset, frame_index in enumerate(newest_first):
            frame = snapshot.frames[frame_index]
            frame_id = offset + 1
            self._frame_ids[frame_id] = frame_index
            _, line, column = self._location_for_frame(snapshot, frame_index)
            frames.append({
                "id": frame_id,
                "name": frame.name,
                "source": self._source_object(),
                "line": max(1, line),
                "column": max(1, column),
                "instructionPointerReference": f"{frame.name}@{frame.instruction_pointer}",
            })
        start = args.get("startFrame", 0)
        levels = args.get("levels", 100)
        if type(start) is not int or start < 0:
            start = 0
        if type(levels) is not int or levels < 0:
            levels = 100
        selected = frames[start:] if levels == 0 else frames[start:start + levels]
        self._response(request, {
            "stackFrames": selected,
            "totalFrames": len(frames),
        })

    def _new_reference(self, kind: str, frame_index: int = -1) -> int:
        reference = self._next_variable_reference
        self._next_variable_reference += 1
        self._variable_references[reference] = (kind, frame_index)
        return reference

    def _handle_scopes(self, request: Mapping[str, Any], args: dict[str, Any]) -> None:
        snapshot = self._paused_snapshot
        frame_id = args.get("frameId")
        frame_index = self._frame_ids.get(frame_id) if type(frame_id) is int else None
        if snapshot is None or frame_index is None:
            self._response(request, {"scopes": []})
            return
        scopes = [
            {
                "name": "Locals",
                "presentationHint": "locals",
                "variablesReference": self._new_reference("locals", frame_index),
                "expensive": False,
            },
            {
                "name": "Globals",
                "presentationHint": "globals",
                "variablesReference": self._new_reference("globals"),
                "expensive": False,
            },
            {
                "name": "Operand Stack",
                "variablesReference": self._new_reference("stack"),
                "expensive": False,
            },
        ]
        self._response(request, {"scopes": scopes})

    def _handle_variables(self, request: Mapping[str, Any], args: dict[str, Any]) -> None:
        reference = args.get("variablesReference")
        entry = self._variable_references.get(reference) if type(reference) is int else None
        snapshot = self._paused_snapshot
        if entry is None or snapshot is None:
            self._response(request, {"variables": []})
            return
        kind, frame_index = entry
        result: list[dict[str, Any]] = []
        if kind == "locals":
            values = snapshot.frames[frame_index].locals
            for local in values:
                value = "<uninitialized>" if not local.initialized else format_value(local.value)
                result.append({
                    "name": local.name,
                    "value": value,
                    "type": local.type_name,
                    "variablesReference": 0,
                })
        elif kind == "globals":
            for name, value in snapshot.globals:
                result.append({
                    "name": name,
                    "value": format_value(value),
                    "type": type(value).__name__,
                    "variablesReference": 0,
                })
        elif kind == "stack":
            for index, value in enumerate(snapshot.operand_stack):
                result.append({
                    "name": f"[{index}]",
                    "value": format_value(value),
                    "type": type(value).__name__,
                    "variablesReference": 0,
                })
        self._response(request, {"variables": result})

    def _handle_evaluate(self, request: Mapping[str, Any], args: dict[str, Any]) -> None:
        expression = args.get("expression")
        snapshot = self._paused_snapshot
        if not isinstance(expression, str) or not _IDENTIFIER.fullmatch(expression) or snapshot is None:
            self._response(
                request, success=False,
                message="Only direct variable-name inspection is supported; expressions are never evaluated.",
            )
            return
        active = snapshot.frames[-1]
        local = next((item for item in active.locals if item.name == expression), None)
        if local is not None:
            if not local.initialized:
                self._response(request, success=False, message=f"Local '{expression}' is not initialized.")
                return
            self._response(request, {
                "result": format_value(local.value),
                "type": local.type_name,
                "variablesReference": 0,
            })
            return
        global_value = dict(snapshot.globals).get(expression)
        if global_value is not None or expression in dict(snapshot.globals):
            self._response(request, {
                "result": format_value(global_value),
                "type": type(global_value).__name__,
                "variablesReference": 0,
            })
            return
        self._response(request, success=False, message=f"Unknown variable '{expression}'.")

    def _should_pause(self, snapshot: InstructionSnapshot) -> str | None:
        if self._terminated:
            raise _AbortDebugSession
        if self._pause_requested:
            self._pause_requested = False
            return "pause"
        line = (
            snapshot.instruction.location.line
            if snapshot.instruction.location is not None else None
        )
        frames = tuple(frame.name for frame in snapshot.frames)
        if self._first_instruction:
            self._first_instruction = False
            if self._stop_on_entry:
                return "entry"

        if self._mode == "continue":
            if line is None or line not in self._breakpoints:
                if self._breakpoint_suppression != (frames, line):
                    self._breakpoint_suppression = None
                return None
            if self._breakpoint_suppression == (frames, line):
                return None
            self._breakpoint_suppression = (frames, line)
            return "breakpoint"

        origin = self._origin
        if origin is None:
            return None
        depth, origin_depth = len(snapshot.frames), len(origin.frames)
        current_location = snapshot.instruction.location
        origin_location = origin.instruction.location
        current_key = (
            None if current_location is None else (
                current_location.start_offset, current_location.end_offset,
                current_location.line, current_location.column,
            )
        )
        origin_key = (
            None if origin_location is None else (
                origin_location.start_offset, origin_location.end_offset,
                origin_location.line, origin_location.column,
            )
        )
        if self._mode == "step_in":
            return "step" if depth != origin_depth or current_key != origin_key else None
        if self._mode == "next":
            if depth < origin_depth:
                return "step"
            if depth > origin_depth:
                return None
            return "step" if current_key != origin_key else None
        if self._mode == "step_out":
            return "step" if depth < origin_depth else None
        return None

    def _on_instruction(self, snapshot: InstructionSnapshot) -> None:
        with self._condition:
            reason = self._should_pause(snapshot)
            if reason is None:
                return
            self._paused_snapshot = snapshot
            self._variable_references.clear()
            self._next_variable_reference = 1
            self._event("stopped", {
                "reason": reason,
                "threadId": 1,
                "allThreadsStopped": True,
                "description": "Rifa'i execution paused.",
            })
            while not self._resume_requested and not self._terminated:
                self._condition.wait()
            if self._terminated:
                raise _AbortDebugSession
            self._mode = self._resume_mode
            if self._mode in {"step_in", "next", "step_out"}:
                self._origin = snapshot
            else:
                self._origin = None
            if self._mode == "continue":
                current_line = (
                    snapshot.instruction.location.line
                    if snapshot.instruction.location is not None else None
                )
                if current_line in self._breakpoints:
                    self._breakpoint_suppression = (
                        tuple(frame.name for frame in snapshot.frames), current_line
                    )
            self._resume_requested = False
            self._paused_snapshot = None
            self._frame_ids.clear()
            self._variable_references.clear()

    def _worker_main(self) -> None:
        exit_code = 0
        try:
            execution = VirtualMachine().execute(
                self._module,
                on_instruction=self._on_instruction,
                debug_symbols=self._debug_symbols,
            )
            for line in execution.output:
                self._event("output", {"category": "stdout", "output": line + "\n"})
        except _AbortDebugSession:
            exit_code = 0
        except OSError:
            # The editor may close its DAP transport while the VM is running.
            self._disconnected = True
            self._terminated = True
            exit_code = 0
        except VMRuntimeError as exc:
            exit_code = 1
            rendered = exc.diagnostic.format(self._source_name)
            self._execution_error = rendered
            try:
                self._event("output", {"category": "stderr", "output": rendered + "\n"})
            except OSError:
                self._disconnected = True
        except BytecodeValidationError as exc:
            exit_code = 1
            rendered = "\n".join(item.format(self._source_name) for item in exc.diagnostics)
            self._execution_error = rendered
            try:
                self._event("output", {"category": "stderr", "output": rendered + "\n"})
            except OSError:
                self._disconnected = True
        except Exception as exc:  # Defensive boundary: never leak a worker traceback over DAP stdout.
            exit_code = 1
            self._execution_error = f"Debug adapter execution failed: {exc}"
            try:
                self._event("output", {"category": "stderr", "output": self._execution_error + "\n"})
            except OSError:
                self._disconnected = True
        finally:
            with self._condition:
                self._worker_finished = True
                self._paused_snapshot = None
                self._condition.notify_all()
                disconnected = self._disconnected
            if not disconnected:
                try:
                    self._event("exited", {"exitCode": exit_code})
                    self._event("terminated", {})
                except OSError:
                    self._disconnected = True

    def _resume(self, request: Mapping[str, Any], mode: str) -> None:
        with self._condition:
            if self._paused_snapshot is None:
                self._response(request, success=False, message="The VM is not paused.")
                return
            self._resume_mode = mode
            self._resume_requested = True
            self._response(
                request,
                {"allThreadsContinued": True} if mode == "continue" else {},
            )
            self._event("continued", {"threadId": 1, "allThreadsContinued": True})
            self._condition.notify_all()

    def _dispatch(self, request: dict[str, Any]) -> bool:
        command = request["command"]
        try:
            args = self._arguments(request)
            if command == "initialize":
                self._response(request, {
                    "supportsConfigurationDoneRequest": True,
                    "supportsConditionalBreakpoints": False,
                    "supportsFunctionBreakpoints": False,
                    "supportsEvaluateForHovers": True,
                    "supportsLoadedSourcesRequest": True,
                    "supportsTerminateRequest": True,
                    "supportsTerminateDebuggee": True,
                    "supportsSetVariable": False,
                })
            elif command == "launch":
                self._load_program(args)
                self._response(request)
                self._initialized = True
                self._event("initialized", {})
            elif command == "setBreakpoints":
                self._handle_set_breakpoints(request, args)
            elif command == "setExceptionBreakpoints":
                self._response(request)
            elif command == "configurationDone":
                self._response(request)
                if self._worker is None:
                    self._worker = Thread(target=self._worker_main, name="rifai-vm", daemon=True)
                    self._worker.start()
            elif command == "threads":
                self._response(request, {"threads": [{"id": 1, "name": "Rifa'i VM"}]})
            elif command == "stackTrace":
                self._handle_stack_trace(request, args)
            elif command == "scopes":
                self._handle_scopes(request, args)
            elif command == "variables":
                self._handle_variables(request, args)
            elif command == "evaluate":
                self._handle_evaluate(request, args)
            elif command == "loadedSources":
                sources = [self._source_object()] if self._module is not None else []
                self._response(request, {"sources": sources})
            elif command == "source":
                reference = args.get("sourceReference")
                if reference == self._source_reference and self._source_reference:
                    self._response(request, {
                        "content": self._source_text,
                        "mimeType": "text/x-rif",
                    })
                else:
                    self._response(request, success=False, message="Unknown source reference.")
            elif command == "continue":
                self._resume(request, "continue")
            elif command == "next":
                self._resume(request, "next")
            elif command == "stepIn":
                self._resume(request, "step_in")
            elif command == "stepOut":
                self._resume(request, "step_out")
            elif command == "pause":
                with self._condition:
                    self._pause_requested = True
                self._response(request)
            elif command == "terminate":
                with self._condition:
                    self._terminated = True
                    self._condition.notify_all()
                self._response(request)
            elif command == "disconnect":
                with self._condition:
                    self._disconnected = True
                    self._terminated = True
                    self._condition.notify_all()
                self._response(request)
                return False
            else:
                self._response(
                    request,
                    success=False,
                    message=f"Unsupported DAP request: {command}",
                )
        except (OSError, UnicodeDecodeError, ValueError, BytecodeFormatError) as exc:
            self._response(request, success=False, message=str(exc))
        except DAPProtocolError as exc:
            self._response(request, success=False, message=str(exc))
        return True

    def run(self) -> int:
        """Process DAP requests until EOF or a disconnect request."""
        try:
            while True:
                request = self._read_message()
                if request is None:
                    break
                if not self._dispatch(request):
                    break
        except DAPProtocolError as exc:
            try:
                self._event("output", {"category": "stderr", "output": f"DAP protocol error: {exc}\n"})
            except OSError:
                pass
            return 2
        finally:
            with self._condition:
                self._disconnected = True
                self._terminated = True
                self._condition.notify_all()
            if self._worker is not None:
                self._worker.join(timeout=2.0)
        return 0


def serve() -> int:
    """Run the Rifa'i Debug Adapter on standard input/output."""
    return RifaIDebugAdapter().run()
