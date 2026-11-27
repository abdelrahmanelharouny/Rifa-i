import pytest

from rifai.bytecode import BytecodeFunction, BytecodeModule, CodeChunk, Instruction, Opcode
from rifai.bytecode.cfg import analyze_module_control_flow, build_control_flow_graph


def test_builds_basic_blocks_and_finds_unreachable_code():
    chunk = CodeChunk(
        "<main>",
        (
            Instruction(Opcode.CONSTANT, 0),
            Instruction(Opcode.JUMP_IF_FALSE, 4),
            Instruction(Opcode.CONSTANT, 1),
            Instruction(Opcode.PRINT),
            Instruction(Opcode.HALT),
            Instruction(Opcode.CONSTANT, 2),
            Instruction(Opcode.HALT),
        ),
    )

    graph = build_control_flow_graph(chunk)

    assert graph.entry_block == 0
    assert [(block.start, block.end) for block in graph.blocks] == [
        (0, 1), (2, 3), (4, 4), (5, 6)
    ]
    assert graph.blocks[0].successors == (4, 2)
    assert graph.reachable_blocks == (0, 2, 4)
    assert graph.unreachable_blocks == (5,)
    assert graph.reachable_instruction_count == 5
    assert graph.unreachable_instruction_count == 2


def test_cfg_handles_loops_without_infinite_traversal():
    chunk = CodeChunk(
        "<main>",
        (
            Instruction(Opcode.JUMP_IF_FALSE, 3),
            Instruction(Opcode.JUMP, 0),
            Instruction(Opcode.HALT),
            Instruction(Opcode.HALT),
        ),
    )

    graph = build_control_flow_graph(chunk)

    assert graph.reachable_blocks == (0, 1, 3)
    assert graph.unreachable_blocks == (2,)


def test_cfg_reports_empty_chunk():
    graph = build_control_flow_graph(CodeChunk("<empty>", ()))

    assert graph.entry_block is None
    assert graph.blocks == ()
    assert graph.reachable_blocks == ()
    assert graph.unreachable_blocks == ()


def test_cfg_rejects_unverified_jump_targets():
    chunk = CodeChunk("<bad>", (Instruction(Opcode.JUMP, 4),))

    with pytest.raises(ValueError, match="Invalid jump target"):
        build_control_flow_graph(chunk)


def test_module_analysis_includes_main_and_function_chunks():
    function = BytecodeFunction(
        "answer",
        CodeChunk("answer", (Instruction(Opcode.CONSTANT, 0), Instruction(Opcode.RETURN))),
        (),
        "int",
    )
    module = BytecodeModule(
        constants=(42,),
        main=CodeChunk("<main>", (Instruction(Opcode.HALT),)),
        functions=(function,),
    )

    graphs = analyze_module_control_flow(module)

    assert tuple(graphs) == ("<main>", "answer")
    assert graphs["answer"].reachable_blocks == (0,)
    assert graphs["<main>"].edge_count == 0


def test_cfg_json_shape_is_deterministic():
    graph = build_control_flow_graph(
        CodeChunk("<main>", (Instruction(Opcode.HALT),))
    )

    assert graph.as_dict() == {
        "chunk": "<main>",
        "entry": 0,
        "block_count": 1,
        "edge_count": 0,
        "reachable_blocks": [0],
        "unreachable_blocks": [],
        "reachable_instruction_count": 1,
        "unreachable_instruction_count": 0,
        "blocks": [{
            "id": 0,
            "start": 0,
            "end": 0,
            "instruction_count": 1,
            "successors": [],
            "reachable": True,
        }],
    }
