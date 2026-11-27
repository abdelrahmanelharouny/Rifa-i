def test_phase5_example_compiles_and_runs():
    from pathlib import Path
    from rifai.compiler import Compiler
    from rifai.vm import VirtualMachine

    example = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "phase5_optimization.rif"
    )
    source = example.read_text(encoding="utf-8")
    result = Compiler().compile(source, source_name=str(example))

    assert result.is_success
    assert VirtualMachine().execute(result.module).output == (
        "Optimized result:",
        "155",
        "20",
    )
