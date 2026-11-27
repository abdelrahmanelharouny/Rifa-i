"""Interactive, source-aware debugger for the Rifa'i virtual machine."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from rifai.bytecode.instructions import Instruction
from rifai.bytecode.module import BytecodeModule
from rifai.vm.machine import InstructionSnapshot, VirtualMachine
from rifai.vm.runtime import ExecutionResult


@dataclass(frozen=True, slots=True)
class DebuggerResult:
    """Outcome of one interactive debugging session."""

    execution: ExecutionResult | None
    aborted: bool


class _AbortExecution(Exception):
    """Internal control-flow signal used by the debugger's quit command."""


def _instruction_label(snapshot: InstructionSnapshot) -> str:
    instruction = snapshot.instruction
    operand = "" if instruction.operand is None else f" {instruction.operand!r}"
    location = instruction.location
    source = (
        f" at {location.line}:{location.column}"
        if location is not None
        else " at <no source map>"
    )
    return (
        f"{snapshot.frame_name} [{snapshot.instruction_index:04d}] "
        f"{instruction.opcode.value}{operand}{source}"
    )


class InteractiveDebugger:
    """Interactive debugger driven by immutable VM instruction snapshots.

    Commands:
      continue / c     Continue until the next breakpoint.
      step / s         Step into the next source expression or call.
      next / n          Step over the current source expression or call.
      out / finish      Run until the current function returns.
      stepi             Execute one bytecode instruction.
      break <line>      Add a source-line breakpoint.
      delete <line>     Remove a source-line breakpoint.
      breakpoints       List all breakpoints.
      locals             Show source-level locals in the active frame.
      stack              Show the operand stack.
      globals            Show global variables.
      backtrace / bt     Show the active call stack.
      list               Show source around the current statement.
      where              Show the current instruction and location.
      help               Show this command summary.
      quit / q           Stop debugging without completing the program.
    """

    def __init__(
        self,
        module: BytecodeModule,
        source: str,
        *,
        debug_symbols: dict[str, dict[int, tuple[str, str]]] | None = None,
        source_name: str = "<memory>",
        breakpoints: Iterable[int] = (),
        vm: VirtualMachine | None = None,
        input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
        list_context: int = 2,
    ) -> None:
        self.module = module
        self.source = source
        self.source_name = source_name
        self.debug_symbols = debug_symbols or {}
        self.breakpoints = set(breakpoints)
        if any(type(line) is not int or line < 1 for line in self.breakpoints):
            raise ValueError("Breakpoint lines must be positive integers.")
        if type(list_context) is not int or list_context < 0:
            raise ValueError("list_context must be a non-negative integer.")
        self.vm = vm or VirtualMachine()
        self.input_fn = input if input_fn is None else input_fn
        self.output_fn = print if output_fn is None else output_fn
        self.list_context = list_context

        self._first_instruction = True
        self._mode = "pause"
        self._origin: InstructionSnapshot | None = None
        self._breakpoint_suppression: tuple[tuple[str, ...], int] | None = None
        self._current: InstructionSnapshot | None = None

    @staticmethod
    def _instruction_key(snapshot: InstructionSnapshot) -> tuple[object, ...]:
        return (
            tuple((frame.name, frame.instruction_pointer) for frame in snapshot.frames),
            snapshot.frame_name,
            snapshot.instruction_index,
        )

    @staticmethod
    def _source_key(snapshot: InstructionSnapshot) -> tuple[object, ...] | None:
        location = snapshot.instruction.location
        if location is None:
            return None
        return (location.start_offset, location.end_offset, location.line, location.column)

    @staticmethod
    def _line(snapshot: InstructionSnapshot) -> int | None:
        location = snapshot.instruction.location
        return location.line if location is not None else None

    def _should_stop(self, snapshot: InstructionSnapshot) -> bool:
        if self._first_instruction:
            self._first_instruction = False
            return True

        if self._mode == "continue":
            line = self._line(snapshot)
            frames = tuple(frame.name for frame in snapshot.frames)
            if line is None or line not in self.breakpoints:
                if self._breakpoint_suppression != (frames, line):
                    self._breakpoint_suppression = None
                return False
            if self._breakpoint_suppression == (frames, line):
                return False
            self._breakpoint_suppression = (frames, line)
            return True

        origin = self._origin
        if origin is None:
            return False
        depth = len(snapshot.frames)
        origin_depth = len(origin.frames)

        if self._mode == "step_instruction":
            return True
        if self._mode == "step_out":
            return depth < origin_depth
        if self._mode == "step_over":
            if depth < origin_depth:
                return True
            if depth > origin_depth:
                return False
            return self._source_key(snapshot) != self._source_key(origin)
        if self._mode == "step_into":
            if depth != origin_depth:
                return True
            return self._source_key(snapshot) != self._source_key(origin)
        return False

    def _on_instruction(self, snapshot: InstructionSnapshot) -> None:
        if not self._should_stop(snapshot):
            return
        self._current = snapshot
        self._show_stop(snapshot)
        self._command_loop(snapshot)

    def _show_stop(self, snapshot: InstructionSnapshot) -> None:
        line = self._line(snapshot)
        reason = "entry" if self._mode == "pause" else (
            "breakpoint" if line in self.breakpoints and self._mode == "continue"
            else "step"
        )
        marker = f"{self.source_name}:{line}" if line is not None else self.source_name
        self.output_fn(f"\nPaused ({reason}) — {marker}")
        self.output_fn(_instruction_label(snapshot))
        self.output_fn(
            f"Call depth: {len(snapshot.frames)} | "
            f"Executed: {snapshot.instructions_executed} instruction(s)"
        )

    def _command_loop(self, snapshot: InstructionSnapshot) -> None:
        while True:
            try:
                raw = self.input_fn("(rifai-debug) ")
            except (EOFError, StopIteration):
                self.output_fn("Debugger input closed; execution aborted.")
                raise _AbortExecution

            parts = raw.strip().split()
            if not parts:
                continue
            command, arguments = parts[0].lower(), parts[1:]

            if command in {"c", "continue", "cont"}:
                self._mode = "continue"
                self._origin = None
                current_line = self._line(snapshot)
                if current_line in self.breakpoints:
                    self._breakpoint_suppression = (
                        tuple(frame.name for frame in snapshot.frames),
                        current_line,
                    )
                return
            if command in {"s", "step", "into"}:
                self._mode = "step_into"
                self._origin = snapshot
                return
            if command in {"n", "next", "over"}:
                self._mode = "step_over"
                self._origin = snapshot
                return
            if command in {"out", "finish"}:
                self._mode = "step_out"
                self._origin = snapshot
                return
            if command in {"stepi", "si"}:
                self._mode = "step_instruction"
                self._origin = snapshot
                return
            if command in {"q", "quit", "exit"}:
                raise _AbortExecution
            if command in {"b", "break"}:
                self._add_breakpoint(arguments)
                continue
            if command in {"d", "delete"}:
                self._delete_breakpoint(arguments)
                continue
            if command in {"breakpoints", "bl"}:
                self._show_breakpoints()
                continue
            if command in {"locals", "l"}:
                self._show_locals(snapshot)
                continue
            if command in {"stack", "operand-stack"}:
                self._show_operand_stack(snapshot)
                continue
            if command in {"globals", "g"}:
                self._show_globals(snapshot)
                continue
            if command in {"backtrace", "bt", "where-stack"}:
                self._show_backtrace(snapshot)
                continue
            if command in {"list", "source"}:
                self._show_source(snapshot)
                continue
            if command in {"where", "w"}:
                self.output_fn(_instruction_label(snapshot))
                continue
            if command in {"h", "help", "?"}:
                self._show_help()
                continue
            self.output_fn(f"Unknown command: {command!r}. Type 'help' for commands.")

    def _add_breakpoint(self, arguments: list[str]) -> None:
        if len(arguments) != 1 or not arguments[0].isdigit() or int(arguments[0]) < 1:
            self.output_fn("Usage: break <positive-source-line>")
            return
        line = int(arguments[0])
        self.breakpoints.add(line)
        self.output_fn(f"Breakpoint added at {self.source_name}:{line}")

    def _delete_breakpoint(self, arguments: list[str]) -> None:
        if len(arguments) != 1 or not arguments[0].isdigit():
            self.output_fn("Usage: delete <source-line>")
            return
        line = int(arguments[0])
        if line in self.breakpoints:
            self.breakpoints.remove(line)
            self.output_fn(f"Breakpoint removed from line {line}")
        else:
            self.output_fn(f"No breakpoint exists at line {line}")

    def _show_breakpoints(self) -> None:
        if not self.breakpoints:
            self.output_fn("No breakpoints.")
            return
        self.output_fn("Breakpoints:")
        for line in sorted(self.breakpoints):
            self.output_fn(f"  {self.source_name}:{line}")

    def _show_locals(self, snapshot: InstructionSnapshot) -> None:
        frame = snapshot.frames[-1]
        self.output_fn(f"Locals in {frame.name}:")
        if not frame.locals:
            self.output_fn("  <no local variables>")
            return
        for item in frame.locals:
            if not item.initialized:
                value = "<uninitialized>"
            else:
                value = repr(item.value)
            self.output_fn(
                f"  {item.name}: {item.type_name} = {value} [slot {item.slot}]"
            )

    def _show_operand_stack(self, snapshot: InstructionSnapshot) -> None:
        self.output_fn("Operand stack (bottom → top):")
        if not snapshot.operand_stack:
            self.output_fn("  <empty>")
            return
        for index, value in enumerate(snapshot.operand_stack):
            self.output_fn(f"  [{index}] {value!r}")

    def _show_globals(self, snapshot: InstructionSnapshot) -> None:
        self.output_fn("Globals:")
        if not snapshot.globals:
            self.output_fn("  <empty>")
            return
        for name, value in snapshot.globals:
            self.output_fn(f"  {name} = {value!r}")

    def _show_backtrace(self, snapshot: InstructionSnapshot) -> None:
        self.output_fn("Call stack (newest frame first):")
        for index, frame in enumerate(reversed(snapshot.frames)):
            location = ""
            if index == 0:
                active = snapshot.instruction.location
                if active is not None:
                    location = f" at {active.line}:{active.column}"
            self.output_fn(
                f"  #{index} {frame.name} ip={frame.instruction_pointer}{location}"
            )

    def _show_source(self, snapshot: InstructionSnapshot) -> None:
        line = self._line(snapshot)
        if line is None:
            self.output_fn("No source location is available for the current instruction.")
            return
        if not self.source:
            self.output_fn("Source text is not embedded in this bytecode module.")
            return
        lines = self.source.splitlines()
        first = max(1, line - self.list_context)
        last = min(len(lines), line + self.list_context)
        for number in range(first, last + 1):
            marker = ">" if number == line else " "
            self.output_fn(f"{marker} {number:4d} | {lines[number - 1]}")

    def _show_help(self) -> None:
        self.output_fn("Execution: continue (c), step (s), next (n), out/finish, stepi, quit (q)")
        self.output_fn("Inspection: locals, stack, globals, backtrace (bt), list, where")
        self.output_fn("Breakpoints: break <line>, delete <line>, breakpoints")

    def run(self) -> DebuggerResult:
        """Run the program under interactive control and return its outcome."""
        try:
            result = self.vm.execute(
                self.module,
                on_instruction=self._on_instruction,
                debug_symbols=self.debug_symbols,
            )
        except _AbortExecution:
            return DebuggerResult(execution=None, aborted=True)
        return DebuggerResult(execution=result, aborted=False)
