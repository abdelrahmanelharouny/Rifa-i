from rifai.bytecode import BytecodeModule, BytecodeSerializer, CodeChunk, Instruction, Opcode
from rifai.cli import main


def write_program(path):
    module = BytecodeModule(
        constants=(42,),
        main=CodeChunk(
            name="<main>",
            instructions=(
                Instruction(Opcode.CONSTANT, 0),
                Instruction(Opcode.PRINT),
                Instruction(Opcode.HALT),
            ),
        ),
        source_name="cli-test.rif",
    )
    BytecodeSerializer.write(module, path)


def test_disasm_command(tmp_path, capsys):
    path = tmp_path / "program.rbc"
    write_program(path)
    assert main(["disasm", str(path)]) == 0
    assert "CONSTANT" in capsys.readouterr().out


def test_vm_command(tmp_path, capsys):
    path = tmp_path / "program.rbc"
    write_program(path)
    assert main(["vm", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "42"


def test_vm_command_rejects_missing_file(tmp_path, capsys):
    path = tmp_path / "missing.rbc"
    assert main(["vm", str(path)]) == 1
    assert "[bytecode]" in capsys.readouterr().err
