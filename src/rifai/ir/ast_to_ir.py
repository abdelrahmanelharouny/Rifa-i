"""Direct AST-to-IR lowering for the Rifa'i compiler.

Unlike BytecodeToIR, this builder consumes the semantically-bound source AST
and creates explicit-value IR directly.  Values are block-local: variables are
represented by typed LOAD/STORE operations, so control-flow edges do not need
to carry expression temporaries or synthesize phi nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rifai.bytecode.instructions import Opcode, SourceLocation
from rifai.bytecode.module import BytecodeDebugInfo, BytecodeDebugLocal
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
    MemberAssignmentStatement,
    MemberExpression,
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
from rifai.frontend.symbol_table import FunctionSymbol, VariableSymbol
from rifai.frontend.tokens import TokenType
from rifai.frontend.types import type_name
from rifai.ir.model import (
    IRBlock,
    IRBranch,
    IRFunction,
    IRHalt,
    IRJump,
    IRLocal,
    IROperation,
    IRModule,
    IRReturn,
    IRValue,
)


_ARRAY_CONSTRUCTORS = {
    "int[]": Opcode.ARRAY_NEW_INT,
    "float[]": Opcode.ARRAY_NEW_FLOAT,
    "bool[]": Opcode.ARRAY_NEW_BOOL,
    "string[]": Opcode.ARRAY_NEW_STRING,
}
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


@dataclass(slots=True)
class _MutableBlock:
    block_id: int
    operations: list[IROperation] = field(default_factory=list)
    terminator: IRJump | IRBranch | IRReturn | IRHalt | None = None


def _walk(root: ASTNode):
    """Yield every AST node that may carry a semantic variable binding."""
    yield root
    if isinstance(root, FunctionDeclaration):
        yield from _walk(root.body)
    elif isinstance(root, BlockStatement):
        for statement in root.statements:
            yield from _walk(statement)
    elif isinstance(root, VariableDeclaration):
        yield from _walk(root.initializer)
    elif isinstance(root, AssignmentStatement):
        yield from _walk(root.value)
    elif isinstance(root, IndexAssignmentStatement):
        yield from _walk(root.array)
        yield from _walk(root.index)
        yield from _walk(root.value)
    elif isinstance(root, MemberAssignmentStatement):
        yield from _walk(root.object)
        yield from _walk(root.value)
    elif isinstance(root, MemberExpression):
        yield from _walk(root.object)
    elif isinstance(root, ArrayLiteralExpression):
        for element in root.elements:
            yield from _walk(element)
    elif isinstance(root, IndexExpression):
        yield from _walk(root.array)
        yield from _walk(root.index)
    elif isinstance(root, IfStatement):
        yield from _walk(root.condition)
        yield from _walk(root.then_branch)
        if root.else_branch is not None:
            yield from _walk(root.else_branch)
    elif isinstance(root, WhileStatement):
        yield from _walk(root.condition)
        yield from _walk(root.body)
    elif isinstance(root, ReturnStatement) and root.value is not None:
        yield from _walk(root.value)
    elif isinstance(root, PrintStatement):
        yield from _walk(root.expression)
    elif isinstance(root, ExpressionStatement):
        yield from _walk(root.expression)
    elif isinstance(root, UnaryExpression):
        yield from _walk(root.operand)
    elif isinstance(root, BinaryExpression):
        yield from _walk(root.left)
        yield from _walk(root.right)
    elif isinstance(root, GroupingExpression):
        yield from _walk(root.expression)
    elif isinstance(root, FunctionCallExpression):
        for argument in root.arguments:
            yield from _walk(argument)


class ASTToIR:
    """Build verified-ready IR directly from a typed and semantically-bound AST."""

    def __init__(self) -> None:
        self._constants: list[int | float | bool | str] = []
        self._constant_indices: dict[tuple[type, object], int] = {}
        self._semantic: SemanticResult | None = None
        self._slots: dict[int, int] = {}
        self._blocks: dict[int, _MutableBlock] = {}
        self._block_order: list[int] = []
        self._current: int | None = None
        self._next_value = 0
        self._function_name = "<main>"

    def build(
        self,
        program: Program,
        semantic: SemanticResult,
        *,
        source_name: str | None = None,
        source_text: str | None = None,
    ) -> IRModule:
        """Translate a valid Program and its matching SemanticResult into IR."""
        if not isinstance(program, Program):
            raise TypeError("program must be a Program.")
        if not isinstance(semantic, SemanticResult):
            raise TypeError("semantic must be a SemanticResult.")
        if not semantic.is_valid:
            raise ValueError("Cannot lower an AST with semantic errors.")

        self._constants = []
        self._constant_indices = {}
        self._semantic = semantic

        declarations = tuple(
            item for item in program.declarations
            if isinstance(item, FunctionDeclaration)
        )
        functions: list[IRFunction] = []
        for declaration in declarations:
            generated = self._build_function(declaration, semantic)
            if generated is not None:
                functions.append(generated)

        main_statements = tuple(
            item for item in program.declarations
            if not isinstance(item, FunctionDeclaration)
        )
        main = self._build_main(main_statements, program.span, semantic)

        local_symbols = ()
        debug_info = BytecodeDebugInfo(
            source_text=source_text,
            local_symbols=tuple(
                (
                    function.name,
                    tuple(
                        BytecodeDebugLocal(item.slot, item.name, item.type_name)
                        for item in function.local_symbols
                    ),
                )
                for function in (main, *functions)
            ),
        )
        return IRModule(
            constants=tuple(self._constants),
            main=main,
            functions=tuple(functions),
            source_name=source_name,
            format_version=4,
            debug_info=debug_info,
        )

    def _reset_function(self, name: str, roots, parameters, semantic: SemanticResult) -> None:
        self._function_name = name
        self._blocks = {}
        self._block_order = []
        self._next_value = 0
        self._slots = self._allocate_slots(roots, parameters, semantic)
        entry = self._new_block()
        if entry != 0:
            raise RuntimeError("IR entry block must have identifier zero.")
        self._current = entry

    @staticmethod
    def _allocate_slots(roots, parameters, semantic: SemanticResult) -> dict[int, int]:
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
            for node in _walk(root):
                if isinstance(node, (VariableDeclaration, AssignmentStatement, VariableExpression)):
                    add(semantic.variable_bindings.get(id(node)))
        return slots

    def _build_main(
        self,
        statements: tuple[Statement, ...],
        program_span: SourceSpan,
        semantic: SemanticResult,
    ) -> IRFunction:
        self._reset_function("<main>", statements, (), semantic)
        self._compile_statements(statements)
        if self._current is None:
            raise RuntimeError("The main program unexpectedly has no exit block.")
        self._terminate(IRHalt(self._location(program_span)))

        # The backend expects entry-first layout and the main HALT in the final
        # block. Explicit terminators make all intermediate layout choices safe.
        terminal = self._current
        order = [0]
        order.extend(
            item for item in self._block_order
            if item not in (0, terminal)
        )
        if terminal != 0:
            order.append(terminal)
        return self._freeze_function(
            name="<main>",
            order=order,
            parameter_types=(),
            return_type="void",
            arity=0,
        )

    def _build_function(
        self,
        declaration: FunctionDeclaration,
        semantic: SemanticResult,
    ) -> IRFunction | None:
        symbol = semantic.function_for(declaration)
        if symbol is None:
            raise ValueError(
                f"Missing semantic binding for function '{declaration.name}'."
            )
        parameters = tuple(symbol.params)
        self._reset_function(
            declaration.name,
            declaration.body.statements,
            parameters,
            semantic,
        )
        self._compile_statements(declaration.body.statements)

        if self._current is not None:
            if symbol.return_type.value == "void":
                self._terminate(IRReturn(None, self._location(declaration.body.span)))
            else:
                # Semantic definite-return analysis guarantees that a valid
                # non-void function cannot reach this point at runtime.
                raise ValueError(
                    f"Non-void function '{declaration.name}' has a reachable fallthrough."
                )

        return self._freeze_function(
            name=symbol.name,
            order=list(self._block_order),
            parameter_types=tuple(item.rifai_type.value for item in symbol.params),
            return_type=symbol.return_type.value,
            arity=len(symbol.params),
        )

    def _freeze_function(
        self,
        *,
        name: str,
        order: list[int],
        parameter_types: tuple[str, ...],
        return_type: str,
        arity: int,
    ) -> IRFunction:
        block_ids = set(self._blocks)
        reachable: set[int] = set()
        pending = [0]
        while pending:
            block_id = pending.pop()
            if block_id in reachable or block_id not in block_ids:
                continue
            reachable.add(block_id)
            term = self._blocks[block_id].terminator
            if isinstance(term, IRJump):
                pending.append(term.target)
            elif isinstance(term, IRBranch):
                pending.extend((term.false_target, term.true_target))

        symbols_by_id = {
            id(symbol): symbol
            for symbol in self._semantic.variable_bindings.values()
        }
        local_symbols = tuple(
            IRLocal(
                slot=slot,
                name=symbols_by_id[symbol_id].name,
                type_name=symbols_by_id[symbol_id].rifai_type.value,
            )
            for symbol_id, slot in sorted(self._slots.items(), key=lambda item: item[1])
            if symbol_id in symbols_by_id
        )

        blocks: list[IRBlock] = []
        for layout_index, block_id in enumerate(order):
            state = self._blocks.get(block_id)
            if state is None:
                continue
            if state.terminator is None:
                raise RuntimeError(
                    f"IR block {block_id} in '{name}' has no terminator."
                )
            blocks.append(
                IRBlock(
                    block_id=block_id,
                    parameters=(),
                    operations=tuple(state.operations),
                    terminator=state.terminator,
                    source_start=layout_index,
                    source_end=layout_index,
                    reachable=block_id in reachable,
                )
            )
        return IRFunction(
            name=name,
            blocks=tuple(blocks),
            local_count=len(self._slots),
            arity=arity,
            parameter_types=parameter_types,
            return_type=return_type,
            local_symbols=local_symbols,
        )

    def _new_block(self) -> int:
        block_id = len(self._block_order)
        self._blocks[block_id] = _MutableBlock(block_id)
        self._block_order.append(block_id)
        return block_id

    def _set_current(self, block_id: int | None) -> None:
        self._current = block_id

    def _terminate(self, terminator: IRJump | IRBranch | IRReturn | IRHalt) -> None:
        if self._current is None:
            raise RuntimeError("Cannot terminate a missing IR insertion block.")
        block = self._blocks[self._current]
        if block.terminator is not None:
            raise RuntimeError(f"IR block {block.block_id} is already terminated.")
        block.terminator = terminator

    def _emit(
        self,
        opcode: Opcode,
        inputs: tuple[int, ...] = (),
        *,
        output_type: str | None = None,
        operand: int | str | None = None,
        span: SourceSpan | None = None,
    ) -> int | None:
        if self._current is None:
            raise RuntimeError("Cannot emit an IR operation without an insertion block.")
        outputs: tuple[IRValue, ...] = ()
        result: int | None = None
        if output_type is not None:
            result = self._next_value
            self._next_value += 1
            outputs = (IRValue(result, output_type),)
        self._blocks[self._current].operations.append(
            IROperation(
                opcode=opcode,
                outputs=outputs,
                inputs=inputs,
                operand=operand,
                location=self._location(span),
            )
        )
        return result

    def _constant_index(self, value: int | float | bool | str) -> int:
        key = (type(value), value)
        existing = self._constant_indices.get(key)
        if existing is not None:
            return existing
        index = len(self._constants)
        self._constants.append(value)
        self._constant_indices[key] = index
        return index

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

    def _type_of(self, expression: Expression) -> str:
        if self._semantic is None:
            raise RuntimeError("ASTToIR has no active semantic result.")
        result = self._semantic.type_of(expression)
        if result is None:
            raise ValueError(
                f"Missing semantic type for {type(expression).__name__}."
            )
        return type_name(result)

    def _variable_symbol(self, node: ASTNode) -> VariableSymbol:
        if self._semantic is None:
            raise RuntimeError("ASTToIR has no active semantic result.")
        symbol = self._semantic.variable_bindings.get(id(node))
        if symbol is None:
            raise ValueError(
                f"Missing semantic variable binding for {type(node).__name__}."
            )
        return symbol

    def _load(self, symbol: VariableSymbol, span: SourceSpan) -> int:
        if symbol.is_global:
            result = self._emit(
                Opcode.LOAD_GLOBAL,
                output_type=type_name(symbol.rifai_type),
                operand=symbol.name,
                span=span,
            )
        else:
            slot = self._slots.get(id(symbol))
            if slot is None:
                raise ValueError(f"No local slot allocated for '{symbol.name}'.")
            result = self._emit(
                Opcode.LOAD_LOCAL,
                output_type=symbol.rifai_type.value,
                operand=slot,
                span=span,
            )
        if result is None:
            raise RuntimeError("Variable load did not produce a value.")
        return result

    def _store(self, symbol: VariableSymbol, value: int, span: SourceSpan) -> None:
        if symbol.is_global:
            self._emit(
                Opcode.STORE_GLOBAL,
                (value,),
                operand=symbol.name,
                span=span,
            )
            return
        slot = self._slots.get(id(symbol))
        if slot is None:
            raise ValueError(f"No local slot allocated for '{symbol.name}'.")
        self._emit(Opcode.STORE_LOCAL, (value,), operand=slot, span=span)

    def _compile_statements(self, statements: tuple[Statement, ...]) -> None:
        for statement in statements:
            if self._current is None:
                break
            self._compile_statement(statement)

    def _compile_statement(self, statement: Statement) -> None:
        if isinstance(statement, VariableDeclaration):
            value = self._compile_value(statement.initializer)
            self._store(self._variable_symbol(statement), value, statement.span)
        elif isinstance(statement, AssignmentStatement):
            value = self._compile_value(statement.value)
            self._store(self._variable_symbol(statement), value, statement.span)
        elif isinstance(statement, IndexAssignmentStatement):
            array = self._compile_value(statement.array)
            index = self._compile_value(statement.index)
            value = self._compile_value(statement.value)
            self._emit(
                Opcode.ARRAY_SET,
                (array, index, value),
                span=statement.span,
            )
        elif isinstance(statement, MemberAssignmentStatement):
            object_value = self._compile_value(statement.object)
            value = self._compile_value(statement.value)
            self._emit(
                Opcode.FIELD_SET,
                (object_value, value),
                operand=statement.name,
                span=statement.span,
            )
        elif isinstance(statement, BlockStatement):
            self._compile_statements(statement.statements)
        elif isinstance(statement, IfStatement):
            self._compile_if(statement)
        elif isinstance(statement, WhileStatement):
            self._compile_while(statement)
        elif isinstance(statement, ReturnStatement):
            value = (
                self._compile_value(statement.value)
                if statement.value is not None
                else None
            )
            self._terminate(IRReturn(value, self._location(statement.span)))
            self._set_current(None)
        elif isinstance(statement, PrintStatement):
            value = self._compile_value(statement.expression)
            self._emit(Opcode.PRINT, (value,), span=statement.span)
        elif isinstance(statement, ExpressionStatement):
            value = self._compile_expression(statement.expression)
            if self._type_of(statement.expression) != "void":
                if value is None:
                    raise ValueError("A value-producing expression did not produce a value.")
                self._emit(Opcode.POP, (value,), span=statement.span)
        elif isinstance(statement, FunctionDeclaration):
            raise ValueError("Nested function declarations are not supported.")

    def _compile_if(self, statement: IfStatement) -> None:
        condition = self._compile_value(statement.condition)
        then_id = self._new_block()
        else_id = (
            self._new_block()
            if statement.else_branch is not None
            else None
        )
        join_id = self._new_block()
        false_target = else_id if else_id is not None else join_id
        self._terminate(
            IRBranch(
                condition=condition,
                false_target=false_target,
                true_target=then_id,
                false_arguments=(),
                true_arguments=(),
                location=self._location(statement.condition.span),
            )
        )

        self._set_current(then_id)
        self._compile_statements(statement.then_branch.statements)
        then_falls_through = self._current is not None
        if then_falls_through:
            self._terminate(
                IRJump(join_id, (), False, self._location(statement.then_branch.span))
            )
            self._set_current(None)

        else_falls_through = False
        if else_id is not None:
            self._set_current(else_id)
            if isinstance(statement.else_branch, BlockStatement):
                self._compile_statements(statement.else_branch.statements)
            elif isinstance(statement.else_branch, IfStatement):
                self._compile_if(statement.else_branch)
            else:
                raise RuntimeError("Unexpected else-branch AST node.")
            else_falls_through = self._current is not None
            if else_falls_through:
                span = statement.else_branch.span
                self._terminate(IRJump(join_id, (), False, self._location(span)))
                self._set_current(None)

        join_is_reachable = (
            then_falls_through
            or (else_falls_through if else_id is not None else True)
        )
        if join_is_reachable:
            self._set_current(join_id)
        else:
            # Both arms terminate. Keep no dead merge block in the IR.
            self._blocks.pop(join_id, None)
            self._block_order.remove(join_id)
            self._set_current(None)

    def _compile_while(self, statement: WhileStatement) -> None:
        condition_id = self._new_block()
        body_id = self._new_block()
        exit_id = self._new_block()
        self._terminate(
            IRJump(condition_id, (), False, self._location(statement.span))
        )

        self._set_current(condition_id)
        condition = self._compile_value(statement.condition)
        self._terminate(
            IRBranch(
                condition=condition,
                false_target=exit_id,
                true_target=body_id,
                false_arguments=(),
                true_arguments=(),
                location=self._location(statement.condition.span),
            )
        )

        self._set_current(body_id)
        self._compile_statements(statement.body.statements)
        if self._current is not None:
            self._terminate(
                IRJump(condition_id, (), False, self._location(statement.body.span))
            )
        self._set_current(exit_id)

    def _compile_value(self, expression: Expression) -> int:
        value = self._compile_expression(expression)
        if value is None:
            raise ValueError(f"Expression '{type(expression).__name__}' has no value.")
        return value

    def _compile_expression(self, expression: Expression) -> int | None:
        result_type = self._type_of(expression)

        if isinstance(expression, LiteralExpression):
            result = self._emit(
                Opcode.CONSTANT,
                output_type=result_type,
                operand=self._constant_index(expression.value),
                span=expression.span,
            )
        elif isinstance(expression, VariableExpression):
            result = self._load(self._variable_symbol(expression), expression.span)
        elif isinstance(expression, GroupingExpression):
            return self._compile_expression(expression.expression)
        elif isinstance(expression, ArrayLiteralExpression):
            values = tuple(
                self._compile_value(item)
                for item in expression.elements
            )
            opcode = _ARRAY_CONSTRUCTORS.get(result_type)
            if opcode is None:
                raise ValueError(f"Unsupported array type '{result_type}'.")
            result = self._emit(
                opcode,
                values,
                output_type=result_type,
                operand=len(values),
                span=expression.span,
            )
        elif isinstance(expression, IndexExpression):
            array = self._compile_value(expression.array)
            index = self._compile_value(expression.index)
            result = self._emit(
                Opcode.ARRAY_GET,
                (array, index),
                output_type=result_type,
                span=expression.span,
            )
        elif isinstance(expression, MemberExpression):
            if self._semantic is None:
                raise RuntimeError("ASTToIR has no active semantic result.")
            enum_variant = self._semantic.enum_variant_bindings.get(id(expression))
            if enum_variant is not None:
                result = self._emit(
                    Opcode.ENUM_NEW,
                    output_type=result_type,
                    operand=enum_variant[0] + "." + enum_variant[1],
                    span=expression.span,
                )
            else:
                object_value = self._compile_value(expression.object)
                result = self._emit(
                    Opcode.FIELD_GET,
                    (object_value,),
                    output_type=result_type,
                    operand=expression.name,
                    span=expression.span,
                )
        elif isinstance(expression, UnaryExpression):
            operand = self._compile_value(expression.operand)
            opcode = (
                Opcode.NEGATE
                if expression.operator.token_type is TokenType.MINUS
                else Opcode.NOT
            )
            result = self._emit(
                opcode,
                (operand,),
                output_type=result_type,
                span=expression.span,
            )
        elif isinstance(expression, BinaryExpression):
            left = self._compile_value(expression.left)
            right = self._compile_value(expression.right)
            opcode = _BINARY_OPCODES.get(expression.operator.token_type)
            if opcode is None:
                raise ValueError(
                    f"Unsupported binary operator '{expression.operator.lexeme}'."
                )
            result = self._emit(
                opcode,
                (left, right),
                output_type=result_type,
                span=expression.span,
            )
        elif isinstance(expression, FunctionCallExpression):
            if self._semantic is None:
                raise RuntimeError("ASTToIR has no active semantic result.")
            struct_declaration = self._semantic.constructor_bindings.get(id(expression))
            if struct_declaration is not None:
                result = self._emit(
                    Opcode.STRUCT_NEW,
                    output_type=result_type,
                    operand=(
                        struct_declaration.name
                        + "|"
                        + ",".join(
                            field.name + ":" + field.type_annotation.name
                            for field in struct_declaration.fields
                        )
                    ),
                    span=expression.span,
                )
                if result is None:
                    raise ValueError("Struct construction did not produce a value.")
                for field, argument in zip(struct_declaration.fields, expression.arguments):
                    duplicate = self._emit(
                        Opcode.DUP,
                        (result,),
                        output_type=result_type,
                        span=expression.span,
                    )
                    value = self._compile_value(argument)
                    self._emit(
                        Opcode.FIELD_SET,
                        (duplicate, value),
                        operand=field.name,
                        span=argument.span,
                    )
            else:
                arguments = tuple(
                    self._compile_value(item)
                    for item in expression.arguments
                )
                if expression.callee == "len":
                    result = self._emit(
                        Opcode.LENGTH,
                        arguments,
                        output_type=result_type,
                        span=expression.span,
                    )
                elif expression.callee == "push":
                    result = self._emit(
                        Opcode.ARRAY_PUSH,
                        arguments,
                        span=expression.span,
                    )
                elif expression.callee == "pop":
                    result = self._emit(
                        Opcode.ARRAY_POP,
                        arguments,
                        output_type=result_type,
                        span=expression.span,
                    )
                else:
                    symbol: FunctionSymbol | None = self._semantic.function_for(expression)
                    result = self._emit(
                        Opcode.CALL,
                        arguments,
                        output_type=None if result_type == "void" else result_type,
                        operand=symbol.name if symbol is not None else expression.callee,
                        span=expression.span,
                    )
        else:
            raise ValueError(
                f"Unsupported expression node '{type(expression).__name__}'."
            )

        if result is None and result_type != "void":
            raise ValueError(
                f"Expression '{type(expression).__name__}' did not produce a value."
            )
        return result
