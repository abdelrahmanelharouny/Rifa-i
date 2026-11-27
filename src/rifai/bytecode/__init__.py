"""Bytecode models, generation, optimization, serialization, and inspection."""

from rifai.bytecode.cfg import BasicBlock, ControlFlowGraph, analyze_module_control_flow, build_control_flow_graph
from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.codegen import CodeGenerationResult, CodeGenerator
from rifai.bytecode.disassembler import disassemble
from rifai.bytecode.instructions import Instruction, Opcode, SourceLocation
from rifai.bytecode.module import (
    BytecodeDebugInfo,
    BytecodeDebugLocal,
    BytecodeModule,
    Constant,
    COLLECTIONS_FORMAT_VERSION,
    DEBUG_INFO_FORMAT_VERSION,
    FORMAT_VERSION,
    FUNCTIONS_FORMAT_VERSION,
    LEGACY_FORMAT_VERSION,
)
from rifai.bytecode.optimizer import (
    BytecodeOptimizer,
    OptimizationResult,
    OptimizationStats,
)
from rifai.bytecode.serializer import BytecodeFormatError, BytecodeSerializer
from rifai.bytecode.verifier import BytecodeValidationResult, BytecodeVerifier

__all__ = [
    "BasicBlock",
    "ControlFlowGraph",
    "analyze_module_control_flow",
    "build_control_flow_graph",
    "BytecodeDebugInfo",
    "BytecodeDebugLocal",
    "BytecodeFormatError",
    "BytecodeFunction",
    "COLLECTIONS_FORMAT_VERSION",
    "DEBUG_INFO_FORMAT_VERSION",
    "BytecodeModule",
    "BytecodeOptimizer",
    "BytecodeSerializer",
    "BytecodeValidationResult",
    "BytecodeVerifier",
    "CodeChunk",
    "CodeGenerationResult",
    "CodeGenerator",
    "Constant",
    "FORMAT_VERSION",
    "FUNCTIONS_FORMAT_VERSION",
    "Instruction",
    "LEGACY_FORMAT_VERSION",
    "Opcode",
    "OptimizationResult",
    "OptimizationStats",
    "SourceLocation",
    "disassemble",
]
