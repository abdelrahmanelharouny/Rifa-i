"""AST-to-bytecode code generation for the Rifa'i language."""

from __future__ import annotations

from dataclasses import dataclass, field

from rifai.bytecode.chunk import BytecodeFunction, CodeChunk
from rifai.bytecode.instructions import Instruction, Opcode, SourceLocation
from rifai.bytecode.module import BytecodeDebugInfo, BytecodeDebugLocal, BytecodeModule
from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import (
    ASTNode,
    ArrayLiteralExpression,
    AssignmentStatement,
    BinaryExpression,
    BlockStatement,
    Expression,
    ExpressionStatement,
    FunctionCallExpression,
    FunctionDeclaration,
    GroupingExpression,
    IndexAssignmentStatement,
    IndexExpression,
    IfStatement,
    LiteralExpression,
    PrintStatement,
    Program,
    ReturnStatement,
    SourceSpan,
    Statement,
    UnaryExpression,
    VariableDeclaration,
    VariableExpression,
    WhileStatement,
)
from rifai.frontend.semantic import SemanticResult
from rifai.frontend.symbol_table import VariableSymbol
from rifai.frontend.tokens import TokenType
from rifai.frontend.types import RifaiType


@dataclass(frozen=True, slots=True)
class CodeGenerationResult:
    """Result of translating a semantically valid AST into bytecode."""

    module: BytecodeModule | None
    diagnostics: tuple[Diagnostic, ...]
    debug_symbols: dict[str, dict[int, tuple[str, str]]] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.module is not None and not self.diagnostics


class CodeGenerator:
    """Generate bytecode using the exact symbol bindings from semantic analysis."""

    _BINARY_OPCODES = {
        TokenType.PLUS: Opcode.ADD,
        TokenType.MINUS: Opcode.SUBTRACT,
        TokenType.STAR: Opcode.MULTIPLY,
        TokenType.SLASH: Opcode.DIVIDE,
        TokenType.MODULO: Opcode.MODULO,
        TokenType.EQUAL_EQUAL: Opcode.EQUAL,
        TokenType.BANG_EQUAL: Opcode.NOT_EQUAL,
        TokenType.LESS: Opcode.LESS,
        TokenType.LESS_EQUAL: Opcode.LESS_EQUAL,
        TokenType.GREATER: Opcode.GREATER,
        TokenType.GREATER_EQUAL: Opcode.GREATER_EQUAL,
        TokenType.AND: Opcode.AND,
        TokenType.OR: Opcode.OR,
    }

    def __init__(self) -> None:
        self._constants: list[int | float | bool | str] = []
        self._constant_indices: dict[tuple[type, object], int] = {}
        self._diagnostics: list[Diagnostic] = []
        self._instructions: list[Instruction] = []
        self._slots: dict[int, int] = {}
        self._debug_symbols: dict[str, dict[int, tuple[str, str]]] = {}
        self._current_function: str | None = None

    def generate(
        self,
        program: Program,
        semantic: SemanticResult,
        *,
        source_name: str | None = None,
        source_text: str | None = None,
    ) -> CodeGenerationResult:
        """Generate a module from an AST and its matching semantic result."""
        self._constants = []
        self._constant_indices = {}
        self._diagnostics = []
        self._debug_symbols = {}

        if not semantic.is_valid:
            return CodeGenerationResult(None, semantic.diagnostics)

        functions: list[BytecodeFunction] = []
        for declaration in program.declarations:
            if isinstance(declaration, FunctionDeclaration):
                generated = self._compile_function(declaration, semantic)
                if generated is not None:
                    functions.append(generated)

        main_statements = tuple(
            declaration
            for declaration in program.declarations
            if not isinstance(declaration, FunctionDeclaration)
        )
        self._slots = self._allocate_slots(main_statements, semantic, ())
        self._debug_symbols["<main>"] = self._describe_slots(self._slots, semantic)
        self._current_function = None
        self._instructions = []
        for statement in main_statements:
            self._compile_statement(statement, semantic)
        self._emit(Opcode.HALT, location=program.span)
        main = CodeChunk(
            name="<main>",
            instructions=tuple(self._instructions),
            local_count=len(self._slots),
            arity=0,
        )

        if self._diagnostics:
            return CodeGenerationResult(None, tuple(self._diagnostics))

        debug_info = BytecodeDebugInfo(
            source_text=source_text,
            local_symbols=tuple(
                (
                    chunk_name,
                    tuple(
                        BytecodeDebugLocal(slot, name, type_name)
                        for slot, (name, type_name) in sorted(symbols.items())
                    ),
                )
                for chunk_name, symbols in sorted(self._debug_symbols.items())
            ),
        )
        module = BytecodeModule(
            constants=tuple(self._constants),
            main=main,
            source_name=source_name,
            functions=tuple(functions),
            debug_info=debug_info,
        )
        return CodeGenerationResult(module, (), dict(self._debug_symbols))

    def _compile_function(
        self,
        declaration: FunctionDeclaration,
        semantic: SemanticResult,
    ) -> BytecodeFunction | None:
        symbol = semantic.function_for(declaration)
        if symbol is None:
            self._error(declaration.span, f"Missing semantic binding for function '{declaration.name}'.")
            return None

        parameter_symbols: list[VariableSymbol] = []
        for parameter in declaration.params:
            bound = semantic.variable_bindings.get(id(parameter))
            if bound is None:
                self._error(parameter.span, f"Missing semantic binding for parameter '{parameter.name}'.")
                continue
            parameter_symbols.append(bound)

        self._slots = self._allocate_slots(
            declaration.body.statements,
            semantic,
            tuple(parameter_symbols),
        )
        self._debug_symbols[declaration.name] = self._describe_slots(self._slots, semantic)
        self._current_function = declaration.name
        self._instructions = []
        for statement in declaration.body.statements:
            self._compile_statement(statement, semantic)

        # Every chunk has an explicit epilogue. For a valid non-void function,
        # semantic definite-return analysis guarantees that this guard is
        # unreachable. The verifier rejects any path that reaches it without
        # the required return value, and jump patching always has an in-range
        # terminal instruction after an if/else chain.
        self._emit(Opcode.RETURN, location=declaration.body.span)

        chunk = CodeChunk(
            name=declaration.name,
            instructions=tuple(self._instructions),
            local_count=len(self._slots),
            arity=len(symbol.params),
        )
        self._current_function = None
        return BytecodeFunction(
            name=symbol.name,
            chunk=chunk,
            parameter_types=tuple(param.rifai_type.value for param in symbol.params),
            return_type=symbol.return_type.value,
        )

    def _allocate_slots(
        self,
        roots: tuple[ASTNode, ...] | tuple[Statement, ...],
        semantic: SemanticResult,
        parameters: tuple[VariableSymbol, ...],
    ) -> dict[int, int]:
        slots: dict[int, int] = {}

        def add(symbol: VariableSymbol | None) -> None:
            if symbol is None or symbol.is_global:
                return
            key = id(symbol)
            if key not in slots:
                slots[key] = len(slots)

        for parameter in parameters:
            add(parameter)

        for root in roots:
            for node in self._walk(root):
                if isinstance(node, (VariableDeclaration, AssignmentStatement, VariableExpression)):
                    add(semantic.variable_bindings.get(id(node)))
        return slots

    @staticmethod
    def _describe_slots(
        slots: dict[int, int],
        semantic: SemanticResult,
    ) -> dict[int, tuple[str, str]]:
        """Build source-level local names for debugger views without changing bytecode."""
        symbols = {
            id(symbol): symbol
            for symbol in semantic.variable_bindings.values()
        }
        return {
            slot: (symbols[symbol_id].name, symbols[symbol_id].rifai_type.value)
            for symbol_id, slot in slots.items()
            if symbol_id in symbols
        }

    @staticmethod
    def _walk(root: ASTNode):
        yield root
        if isinstance(root, FunctionDeclaration):
            yield from CodeGenerator._walk(root.body)
        elif isinstance(root, BlockStatement):
            for statement in root.statements:
                yield from CodeGenerator._walk(statement)
        elif isinstance(root, VariableDeclaration):
            yield from CodeGenerator._walk(root.initializer)
        elif isinstance(root, AssignmentStatement):
            yield from CodeGenerator._walk(root.value)
        elif isinstance(root, IndexAssignmentStatement):
            yield from CodeGenerator._walk(root.array)
            yield from CodeGenerator._walk(root.index)
            yield from CodeGenerator._walk(root.value)
        elif isinstance(root, ArrayLiteralExpression):
            for element in root.elements:
                yield from CodeGenerator._walk(element)
        elif isinstance(root, IndexExpression):
            yield from CodeGenerator._walk(root.array)
            yield from CodeGenerator._walk(root.index)
        elif isinstance(root, IfStatement):
            yield from CodeGenerator._walk(root.condition)
            yield from CodeGenerator._walk(root.then_branch)
            if root.else_branch is not None:
                yield from CodeGenerator._walk(root.else_branch)
        elif isinstance(root, WhileStatement):
            yield from CodeGenerator._walk(root.condition)
            yield from CodeGenerator._walk(root.body)
        elif isinstance(root, ReturnStatement) and root.value is not None:
            yield from CodeGenerator._walk(root.value)
        elif isinstance(root, PrintStatement):
            yield from CodeGenerator._walk(root.expression)
        elif isinstance(root, ExpressionStatement):
            yield from CodeGenerator._walk(root.expression)
        elif isinstance(root, UnaryExpression):
            yield from CodeGenerator._walk(root.operand)
        elif isinstance(root, BinaryExpression):
            yield from CodeGenerator._walk(root.left)
            yield from CodeGenerator._walk(root.right)
        elif isinstance(root, GroupingExpression):
            yield from CodeGenerator._walk(root.expression)
        elif isinstance(root, FunctionCallExpression):
            for argument in root.arguments:
                yield from CodeGenerator._walk(argument)

    def _error(self, span: SourceSpan, message: str) -> None:
        self._diagnostics.append(
            Diagnostic(
                phase=DiagnosticPhase.BYTECODE,
                message=message,
                line=span.line,
                column=span.column,
                start_offset=span.start_offset,
                end_offset=span.end_offset,
            )
        )

    @staticmethod
    def _location(span: SourceSpan | None) -> SourceLocation | None:
        if span is None:
            return None
        return SourceLocation(
            line=span.line,
            column=span.column,
            start_offset=span.start_offset,
            end_offset=span.end_offset,
        )

    def _emit(
        self,
        opcode: Opcode,
        operand: int | str | None = None,
        *,
        location: SourceSpan | None = None,
    ) -> int:
        self._instructions.append(
            Instruction(opcode, operand, self._location(location))
        )
        return len(self._instructions) - 1

    def _patch_jump(self, instruction_index: int, target: int) -> None:
        original = self._instructions[instruction_index]
        self._instructions[instruction_index] = Instruction(
            original.opcode,
            target,
            original.location,
        )

    def _constant_index(self, value: int | float | bool | str) -> int:
        key = (type(value), value)
        existing = self._constant_indices.get(key)
        if existing is not None:
            return existing
        index = len(self._constants)
        self._constants.append(value)
        self._constant_indices[key] = index
        return index

    def _variable_symbol(self, node: ASTNode, semantic: SemanticResult) -> VariableSymbol | None:
        symbol = semantic.variable_bindings.get(id(node))
        if symbol is None:
            span = getattr(node, "span", None)
            if isinstance(span, SourceSpan):
                self._error(span, "Missing variable binding during bytecode generation.")
        return symbol

    def _load_variable(self, symbol: VariableSymbol, span: SourceSpan) -> None:
        if symbol.is_global:
            self._emit(Opcode.LOAD_GLOBAL, symbol.name, location=span)
            return
        slot = self._slots.get(id(symbol))
        if slot is None:
            self._error(span, f"No local slot allocated for variable '{symbol.name}'.")
            return
        self._emit(Opcode.LOAD_LOCAL, slot, location=span)

    def _store_variable(self, symbol: VariableSymbol, span: SourceSpan) -> None:
        if symbol.is_global:
            self._emit(Opcode.STORE_GLOBAL, symbol.name, location=span)
            return
        slot = self._slots.get(id(symbol))
        if slot is None:
            self._error(span, f"No local slot allocated for variable '{symbol.name}'.")
            return
        self._emit(Opcode.STORE_LOCAL, slot, location=span)

    def _compile_statement(self, statement: Statement, semantic: SemanticResult) -> None:
        if isinstance(statement, VariableDeclaration):
            self._compile_expression(statement.initializer, semantic)
            symbol = self._variable_symbol(statement, semantic)
            if symbol is not None:
                self._store_variable(symbol, statement.span)
        elif isinstance(statement, AssignmentStatement):
            self._compile_expression(statement.value, semantic)
            symbol = self._variable_symbol(statement, semantic)
            if symbol is not None:
                self._store_variable(symbol, statement.span)
        elif isinstance(statement, IndexAssignmentStatement):
            self._compile_expression(statement.array, semantic)
            self._compile_expression(statement.index, semantic)
            self._compile_expression(statement.value, semantic)
            self._emit(Opcode.ARRAY_SET, location=statement.span)
        elif isinstance(statement, BlockStatement):
            for nested in statement.statements:
                self._compile_statement(nested, semantic)
        elif isinstance(statement, IfStatement):
            self._compile_if(statement, semantic)
        elif isinstance(statement, WhileStatement):
            self._compile_while(statement, semantic)
        elif isinstance(statement, ReturnStatement):
            if statement.value is not None:
                self._compile_expression(statement.value, semantic)
            self._emit(Opcode.RETURN, location=statement.span)
        elif isinstance(statement, PrintStatement):
            self._compile_expression(statement.expression, semantic)
            self._emit(Opcode.PRINT, location=statement.span)
        elif isinstance(statement, ExpressionStatement):
            self._compile_expression(statement.expression, semantic)
            expr_type = semantic.type_of(statement.expression)
            if expr_type is not RifaiType.VOID:
                self._emit(Opcode.POP, location=statement.span)

    def _compile_if(self, statement: IfStatement, semantic: SemanticResult) -> None:
        self._compile_expression(statement.condition, semantic)
        false_jump = self._emit(
            Opcode.JUMP_IF_FALSE,
            -1,
            location=statement.condition.span,
        )
        for nested in statement.then_branch.statements:
            self._compile_statement(nested, semantic)

        if statement.else_branch is None:
            self._patch_jump(false_jump, len(self._instructions))
            return

        end_jump = self._emit(Opcode.JUMP, -1, location=statement.span)
        self._patch_jump(false_jump, len(self._instructions))
        if isinstance(statement.else_branch, BlockStatement):
            for nested in statement.else_branch.statements:
                self._compile_statement(nested, semantic)
        else:
            self._compile_if(statement.else_branch, semantic)
        self._patch_jump(end_jump, len(self._instructions))

    def _compile_while(self, statement: WhileStatement, semantic: SemanticResult) -> None:
        loop_start = len(self._instructions)
        self._compile_expression(statement.condition, semantic)
        exit_jump = self._emit(
            Opcode.JUMP_IF_FALSE,
            -1,
            location=statement.condition.span,
        )
        for nested in statement.body.statements:
            self._compile_statement(nested, semantic)
        self._emit(Opcode.JUMP, loop_start, location=statement.span)
        self._patch_jump(exit_jump, len(self._instructions))

    def _compile_expression(self, expression: Expression, semantic: SemanticResult) -> None:
        if isinstance(expression, LiteralExpression):
            self._emit(
                Opcode.CONSTANT,
                self._constant_index(expression.value),
                location=expression.span,
            )
        elif isinstance(expression, VariableExpression):
            symbol = self._variable_symbol(expression, semantic)
            if symbol is not None:
                self._load_variable(symbol, expression.span)
        elif isinstance(expression, GroupingExpression):
            self._compile_expression(expression.expression, semantic)
        elif isinstance(expression, ArrayLiteralExpression):
            for element in expression.elements:
                self._compile_expression(element, semantic)
            array_type = semantic.type_of(expression)
            array_opcodes = {
                "int[]": Opcode.ARRAY_NEW_INT,
                "float[]": Opcode.ARRAY_NEW_FLOAT,
                "bool[]": Opcode.ARRAY_NEW_BOOL,
                "string[]": Opcode.ARRAY_NEW_STRING,
            }
            opcode = array_opcodes.get(array_type.value if array_type is not None else "")
            if opcode is None:
                self._error(expression.span, "Could not determine array element type during code generation.")
            else:
                self._emit(opcode, len(expression.elements), location=expression.span)
        elif isinstance(expression, IndexExpression):
            self._compile_expression(expression.array, semantic)
            self._compile_expression(expression.index, semantic)
            self._emit(Opcode.ARRAY_GET, location=expression.span)
        elif isinstance(expression, UnaryExpression):
            self._compile_expression(expression.operand, semantic)
            opcode = (
                Opcode.NEGATE
                if expression.operator.token_type is TokenType.MINUS
                else Opcode.NOT
            )
            self._emit(opcode, location=expression.span)
        elif isinstance(expression, BinaryExpression):
            self._compile_expression(expression.left, semantic)
            self._compile_expression(expression.right, semantic)
            opcode = self._BINARY_OPCODES.get(expression.operator.token_type)
            if opcode is None:
                self._error(expression.span, f"Unsupported binary operator '{expression.operator.lexeme}'.")
            else:
                self._emit(opcode, location=expression.span)
        elif isinstance(expression, FunctionCallExpression):
            for argument in expression.arguments:
                self._compile_expression(argument, semantic)
            if expression.callee == "len":
                self._emit(Opcode.LENGTH, location=expression.span)
            elif expression.callee == "push":
                self._emit(Opcode.ARRAY_PUSH, location=expression.span)
            elif expression.callee == "pop":
                self._emit(Opcode.ARRAY_POP, location=expression.span)
            else:
                symbol = semantic.function_for(expression)
                if symbol is None:
                    self._error(expression.span, f"Missing semantic binding for function '{expression.callee}'.")
                else:
                    self._emit(Opcode.CALL, symbol.name, location=expression.span)
        else:
            self._error(expression.span, f"Unsupported expression node '{type(expression).__name__}'.")
