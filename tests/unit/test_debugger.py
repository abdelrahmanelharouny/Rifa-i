from __future__ import annotations

from rifai import Compiler
from rifai.bytecode.instructions import Instruction, Opcode, SourceLocation
from rifai.vm.debugger import InteractiveDebugger
from rifai.vm.machine import (
    DebugFrameSnapshot,
    InstructionSnapshot,
    VirtualMachine,
)

SOURCE = """fn add(a: int, b: int) -> int {
    let result: int = a + b;
    return result;
}
let total: int = add(20, 22);
print(total);
"""


def test_vm_instruction_observer_exposes_real_call_frames_and_named_locals() -> None:
    compiled = Compiler(optimize=False).compile(SOURCE, source_name="debug.rif")
    assert compiled.is_success and compiled.module is not None
    snapshots: list[InstructionSnapshot] = []

    execution = VirtualMachine().execute(
        compiled.module,
        on_instruction=snapshots.append,
        debug_symbols=compiled.debug_symbols,
    )

    assert execution.output == ("42",)
    assert len(snapshots) == execution.instructions_executed
    inside = next(
        item for item in snapshots
        if item.frame_name == "add"
        and item.instruction.opcode is Opcode.LOAD_LOCAL
        and any(local.name == "result" and local.initialized for local in item.frames[-1].locals)
    )
    assert [frame.name for frame in inside.frames] == ["<main>", "add"]
    locals_by_name = {item.name: item for item in inside.frames[-1].locals}
    assert locals_by_name["a"].value == 20
    assert locals_by_name["b"].value == 22
    assert locals_by_name["result"].value == 42
    assert inside.instruction.location is not None
    assert inside.operand_stack == ()


def _snapshot(
    *,
    frame_names: tuple[str, ...] = ("<main>",),
    ip: int = 0,
    line: int = 1,
    start: int = 0,
    end: int = 1,
) -> InstructionSnapshot:
    frames = tuple(
        DebugFrameSnapshot(
            name=name,
            instruction_pointer=ip if index == len(frame_names) - 1 else 0,
            stack_base=0,
            is_main=index == 0,
            locals=(),
        )
        for index, name in enumerate(frame_names)
    )
    return InstructionSnapshot(
        instruction=Instruction(
            Opcode.HALT,
            location=SourceLocation(line, 1, start, end),
        ),
        frame_name=frame_names[-1],
        instruction_index=ip,
        frames=frames,
        operand_stack=(),
        globals=(),
        instructions_executed=ip,
    )


def _debugger() -> InteractiveDebugger:
    compiled = Compiler(optimize=False).compile("print(1);")
    assert compiled.module is not None
    return InteractiveDebugger(compiled.module, "print(1);", input_fn=lambda _: "quit")


def test_step_into_over_and_out_stop_at_expected_frame_or_source_transition() -> None:
    debugger = _debugger()
    origin = _snapshot()

    debugger._first_instruction = False
    debugger._mode = "step_into"
    debugger._origin = origin
    assert not debugger._should_stop(_snapshot(ip=1, start=0, end=1))
    assert debugger._should_stop(_snapshot(ip=2, line=2, start=5, end=6))
    assert debugger._should_stop(_snapshot(frame_names=("<main>", "callee"), line=1))

    debugger._mode = "step_over"
    debugger._origin = origin
    assert not debugger._should_stop(_snapshot(frame_names=("<main>", "callee"), line=2))
    assert debugger._should_stop(_snapshot(ip=3, line=2, start=5, end=6))

    debugger._mode = "step_out"
    debugger._origin = _snapshot(frame_names=("<main>", "outer", "inner"))
    assert debugger._should_stop(_snapshot(frame_names=("<main>", "outer")))
    assert debugger._should_stop(_snapshot(frame_names=("<main>",)))


def test_line_breakpoint_stops_once_per_line_visit_not_for_each_opcode() -> None:
    debugger = _debugger()
    debugger.breakpoints = {4}
    debugger._first_instruction = False
    debugger._mode = "continue"

    assert debugger._should_stop(_snapshot(ip=1, line=4, start=10, end=20))
    assert not debugger._should_stop(_snapshot(ip=2, line=4, start=10, end=20))
    assert not debugger._should_stop(_snapshot(ip=3, line=5, start=21, end=22))
    assert debugger._should_stop(_snapshot(ip=4, line=4, start=10, end=20))


def test_interactive_debugger_inspects_function_locals_and_finishes_program() -> None:
    compiled = Compiler(optimize=False).compile(SOURCE, source_name="debug.rif")
    assert compiled.module is not None
    commands = iter(["continue", "locals", "backtrace", "stack", "continue"])
    output: list[str] = []
    debugger = InteractiveDebugger(
        compiled.module,
        SOURCE,
        debug_symbols=compiled.debug_symbols,
        source_name="debug.rif",
        breakpoints=[2],
        input_fn=lambda _: next(commands),
        output_fn=output.append,
    )

    result = debugger.run()

    assert result.aborted is False
    assert result.execution is not None
    assert result.execution.output == ("42",)
    rendered = "\n".join(output)
    assert "Paused (breakpoint) — debug.rif:2" in rendered
    assert "a: int = 20" in rendered
    assert "b: int = 22" in rendered
    assert "result: int = <uninitialized>" in rendered
    assert "Call stack (newest frame first)" in rendered
    assert "add" in rendered


def test_quit_aborts_before_program_finishes() -> None:
    compiled = Compiler(optimize=False).compile("print(42);")
    assert compiled.module is not None
    debugger = InteractiveDebugger(
        compiled.module,
        "print(42);",
        input_fn=lambda _: "quit",
        output_fn=lambda _: None,
    )
    result = debugger.run()
    assert result.aborted is True
    assert result.execution is None
