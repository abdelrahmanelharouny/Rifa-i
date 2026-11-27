"""Semantic analyzer and static type checker for the Rifa'i language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import (
    AssignmentStatement,
    BinaryExpression,
    BlockStatement,
    Expression,
    ExpressionStatement,
    FunctionCallExpression,
    FunctionDeclaration,
    GroupingExpression,
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
from rifai.frontend.symbol_table import FunctionSymbol, SymbolTable, VariableSymbol
from rifai.frontend.tokens import TokenType
from rifai.frontend.types import (
    RifaiType,
    is_error_type,
    is_numeric,
    is_value_type,
    type_from_name,
)

_RELATIONAL_OPS: Final[frozenset[TokenType]] = frozenset(
    {
        TokenType.LESS,
        TokenType.LESS_EQUAL,
        TokenType.GREATER,
        TokenType.GREATER_EQUAL,
    }
)

_EQUALITY_OPS: Final[frozenset[TokenType]] = frozenset(
    {
        TokenType.EQUAL_EQUAL,
        TokenType.BANG_EQUAL,
    }
)


@dataclass(frozen=True, slots=True)
class SemanticResult:
    """Validated semantic model produced by the Rifa'i SemanticAnalyzer."""

    diagnostics: tuple[Diagnostic, ...]
    expression_types: dict[int, RifaiType]
    variable_bindings: dict[int, VariableSymbol]
    function_bindings: dict[int, FunctionSymbol]
    global_symbols: dict[str, VariableSymbol | FunctionSymbol]

    @property
    def is_valid(self) -> bool:
        """Return True when semantic analysis completed with zero diagnostics."""
        return len(self.diagnostics) == 0

    def type_of(self, expression: Expression) -> RifaiType | None:
        """Return the inferred RifaiType for an AST expression node."""
        return self.expression_types.get(id(expression))

    def variable_for(
        self,
        node: VariableDeclaration | AssignmentStatement | VariableExpression,
    ) -> VariableSymbol | None:
        """Return the resolved VariableSymbol for a declaration, assignment, or reference."""
        return self.variable_bindings.get(id(node))

    def function_for(
        self, node: FunctionDeclaration | FunctionCallExpression
    ) -> FunctionSymbol | None:
        """Return the resolved FunctionSymbol for a declaration or call."""
        return self.function_bindings.get(id(node))


class SemanticAnalyzer:
    """Performs scope resolution, static type checking, and return-path validation."""

    def __init__(self) -> None:
        self._symbol_table = SymbolTable()
        self._diagnostics: list[Diagnostic] = []
        self._expression_types: dict[int, RifaiType] = {}
        self._variable_bindings: dict[int, VariableSymbol] = {}
        self._function_bindings: dict[int, FunctionSymbol] = {}
        self._current_function: FunctionSymbol | None = None

    def analyze(self, program: Program) -> SemanticResult:
        """Analyze a parsed Rifa'i Program AST and return a SemanticResult."""
        self._symbol_table = SymbolTable()
        self._diagnostics = []
        self._expression_types = {}
        self._variable_bindings = {}
        self._function_bindings = {}
        self._current_function = None

        self._collect_function_signatures(program)

        for decl in program.declarations:
            if isinstance(decl, FunctionDeclaration):
                self._analyze_function_declaration(decl)
            else:
                self._analyze_statement(decl)

        return SemanticResult(
            diagnostics=tuple(self._diagnostics),
            expression_types=dict(self._expression_types),
            variable_bindings=dict(self._variable_bindings),
            function_bindings=dict(self._function_bindings),
            global_symbols=self._symbol_table.global_scope.symbols,
        )

    def _error(self, span: SourceSpan, message: str) -> None:
        self._diagnostics.append(
            Diagnostic(
                phase=DiagnosticPhase.SEMANTIC,
                message=message,
                line=span.line,
                column=span.column,
                start_offset=span.start_offset,
                end_offset=span.end_offset,
            )
        )

    # --- Pass 1: Function signature collection -------------------------------

    def _collect_function_signatures(self, program: Program) -> None:
        for decl in program.declarations:
            if not isinstance(decl, FunctionDeclaration):
                continue

            return_type = type_from_name(decl.return_type.name)
            if return_type is None:
                self._error(
                    decl.return_type.span,
                    f"Unknown return type '{decl.return_type.name}'.",
                )
                return_type = RifaiType.ERROR

            params: list[VariableSymbol] = []
            seen_params: set[str] = set()
            for param in decl.params:
                param_type = type_from_name(param.type_annotation.name)
                if param_type is None:
                    self._error(
                        param.type_annotation.span,
                        f"Unknown parameter type '{param.type_annotation.name}'.",
                    )
                    param_type = RifaiType.ERROR
                elif param_type is RifaiType.VOID:
                    self._error(
                        param.type_annotation.span,
                        f"Parameter '{param.name}' cannot have type 'void'.",
                    )
                    param_type = RifaiType.ERROR

                if param.name in seen_params:
                    self._error(
                        SourceSpan.from_token(param.name_token),
                        f"Duplicate parameter name '{param.name}' in function '{decl.name}'.",
                    )
                else:
                    seen_params.add(param.name)

                params.append(
                    VariableSymbol(
                        name=param.name,
                        rifai_type=param_type,
                        declaration_span=param.span,
                        is_parameter=True,
                        is_global=False,
                        scope_depth=1,
                    )
                )

            func_symbol = FunctionSymbol(
                name=decl.name,
                params=tuple(params),
                return_type=return_type,
                declaration_span=decl.span,
            )

            if not self._symbol_table.define_function(func_symbol):
                self._error(
                    SourceSpan.from_token(decl.name_token),
                    f"Duplicate declaration of function '{decl.name}'.",
                )
            else:
                self._function_bindings[id(decl)] = func_symbol

    # --- Pass 2: Function bodies & statements --------------------------------

    def _analyze_function_declaration(self, decl: FunctionDeclaration) -> None:
        func_symbol = self._function_bindings.get(id(decl))
        if func_symbol is None:
            # Duplicate function signature already reported in pass 1.
            return

        previous_function = self._current_function
        self._current_function = func_symbol
        self._symbol_table.enter_scope(f"fn:{decl.name}")
        try:
            for param_node, param_sym in zip(decl.params, func_symbol.params):
                if self._symbol_table.resolve_local(param_sym.name) is None:
                    self._symbol_table.define_variable(param_sym)
                    self._variable_bindings[id(param_node)] = param_sym

            for stmt in decl.body.statements:
                self._analyze_statement(stmt)

            if (
                func_symbol.return_type not in (RifaiType.VOID, RifaiType.ERROR)
                and not self._definitely_returns(decl.body)
            ):
                self._error(
                    SourceSpan.from_token(decl.name_token),
                    f"Function '{decl.name}' with return type '{func_symbol.return_type.value}' "
                    "must return a value on all execution paths.",
                )
        finally:
            self._symbol_table.exit_scope()
            self._current_function = previous_function

    def _analyze_statement(self, stmt: Statement) -> None:
        if isinstance(stmt, VariableDeclaration):
            self._analyze_variable_declaration(stmt)
        elif isinstance(stmt, AssignmentStatement):
            self._analyze_assignment(stmt)
        elif isinstance(stmt, BlockStatement):
            self._analyze_block(stmt)
        elif isinstance(stmt, IfStatement):
            self._analyze_if(stmt)
        elif isinstance(stmt, WhileStatement):
            self._analyze_while(stmt)
        elif isinstance(stmt, ReturnStatement):
            self._analyze_return(stmt)
        elif isinstance(stmt, PrintStatement):
            self._analyze_print(stmt)
        elif isinstance(stmt, ExpressionStatement):
            self._analyze_expression(stmt.expression)
        elif isinstance(stmt, FunctionDeclaration):
            self._error(stmt.span, "Nested function declarations are not allowed.")

    def _analyze_variable_declaration(self, stmt: VariableDeclaration) -> None:
        declared_type = type_from_name(stmt.type_annotation.name)
        if declared_type is None:
            self._error(
                stmt.type_annotation.span,
                f"Unknown type '{stmt.type_annotation.name}'.",
            )
            declared_type = RifaiType.ERROR
        elif declared_type is RifaiType.VOID:
            self._error(
                stmt.type_annotation.span,
                f"Variable '{stmt.name}' cannot have type 'void'.",
            )
            declared_type = RifaiType.ERROR

        init_type = self._analyze_expression(stmt.initializer)
        if (
            not is_error_type(declared_type)
            and not is_error_type(init_type)
            and init_type is not declared_type
        ):
            self._error(
                stmt.initializer.span,
                f"Cannot initialize variable '{stmt.name}' of type '{declared_type.value}' "
                f"with value of type '{init_type.value}'.",
            )

        scope = self._symbol_table.current_scope
        var_symbol = VariableSymbol(
            name=stmt.name,
            rifai_type=declared_type,
            declaration_span=stmt.span,
            is_parameter=False,
            is_global=(scope.depth == 0),
            scope_depth=scope.depth,
        )

        if not self._symbol_table.define_variable(var_symbol):
            existing = self._symbol_table.resolve_local(stmt.name)
            if isinstance(existing, FunctionSymbol):
                self._error(
                    SourceSpan.from_token(stmt.name_token),
                    f"Global variable '{stmt.name}' conflicts with existing function '{stmt.name}'.",
                )
            else:
                self._error(
                    SourceSpan.from_token(stmt.name_token),
                    f"Duplicate declaration of variable '{stmt.name}' in the same scope.",
                )
        else:
            self._variable_bindings[id(stmt)] = var_symbol

    def _analyze_assignment(self, stmt: AssignmentStatement) -> None:
        value_type = self._analyze_expression(stmt.value)
        symbol = self._symbol_table.resolve(stmt.name)
        if symbol is None:
            self._error(
                SourceSpan.from_token(stmt.name_token),
                f"Undefined variable '{stmt.name}'.",
            )
            return
        if isinstance(symbol, FunctionSymbol):
            self._error(
                SourceSpan.from_token(stmt.name_token),
                f"Cannot assign to function '{stmt.name}'.",
            )
            return

        self._variable_bindings[id(stmt)] = symbol
        if (
            not is_error_type(symbol.rifai_type)
            and not is_error_type(value_type)
            and value_type is not symbol.rifai_type
        ):
            self._error(
                stmt.value.span,
                f"Cannot assign value of type '{value_type.value}' to variable "
                f"'{stmt.name}' of type '{symbol.rifai_type.value}'.",
            )

    def _analyze_block(self, block: BlockStatement) -> None:
        self._symbol_table.enter_scope("block")
        try:
            for stmt in block.statements:
                self._analyze_statement(stmt)
        finally:
            self._symbol_table.exit_scope()

    def _analyze_if(self, stmt: IfStatement) -> None:
        cond_type = self._analyze_expression(stmt.condition)
        if not is_error_type(cond_type) and cond_type is not RifaiType.BOOL:
            self._error(
                stmt.condition.span,
                f"'if' condition must have type 'bool', got '{cond_type.value}'.",
            )

        self._analyze_block(stmt.then_branch)
        if isinstance(stmt.else_branch, BlockStatement):
            self._analyze_block(stmt.else_branch)
        elif isinstance(stmt.else_branch, IfStatement):
            self._analyze_if(stmt.else_branch)

    def _analyze_while(self, stmt: WhileStatement) -> None:
        cond_type = self._analyze_expression(stmt.condition)
        if not is_error_type(cond_type) and cond_type is not RifaiType.BOOL:
            self._error(
                stmt.condition.span,
                f"'while' condition must have type 'bool', got '{cond_type.value}'.",
            )
        self._analyze_block(stmt.body)

    def _analyze_return(self, stmt: ReturnStatement) -> None:
        if self._current_function is None:
            if stmt.value is not None:
                self._analyze_expression(stmt.value)
            self._error(
                stmt.span, "Return statement is only allowed inside a function."
            )
            return

        expected = self._current_function.return_type
        if expected is RifaiType.VOID:
            if stmt.value is not None:
                self._analyze_expression(stmt.value)
                self._error(
                    stmt.value.span,
                    f"Void function '{self._current_function.name}' cannot return a value.",
                )
            return

        if stmt.value is None:
            self._error(
                stmt.span,
                f"Non-void function '{self._current_function.name}' must return a value "
                f"of type '{expected.value}'.",
            )
            return

        actual = self._analyze_expression(stmt.value)
        if (
            not is_error_type(expected)
            and not is_error_type(actual)
            and actual is not expected
        ):
            self._error(
                stmt.value.span,
                f"Return type mismatch in function '{self._current_function.name}': "
                f"expected '{expected.value}', got '{actual.value}'.",
            )

    def _analyze_print(self, stmt: PrintStatement) -> None:
        expr_type = self._analyze_expression(stmt.expression)
        if expr_type is RifaiType.VOID:
            self._error(
                stmt.expression.span, "Cannot print an expression of type 'void'."
            )

    # --- Expressions ---------------------------------------------------------

    def _analyze_expression(self, expr: Expression) -> RifaiType:
        result_type: RifaiType

        if isinstance(expr, LiteralExpression):
            result_type = self._type_of_literal(expr)
        elif isinstance(expr, VariableExpression):
            result_type = self._analyze_variable_expr(expr)
        elif isinstance(expr, GroupingExpression):
            result_type = self._analyze_expression(expr.expression)
        elif isinstance(expr, UnaryExpression):
            result_type = self._analyze_unary(expr)
        elif isinstance(expr, BinaryExpression):
            result_type = self._analyze_binary(expr)
        elif isinstance(expr, FunctionCallExpression):
            result_type = self._analyze_call(expr)
        else:
            result_type = RifaiType.ERROR

        self._expression_types[id(expr)] = result_type
        return result_type

    @staticmethod
    def _type_of_literal(expr: LiteralExpression) -> RifaiType:
        if isinstance(expr.value, bool):
            return RifaiType.BOOL
        if isinstance(expr.value, int):
            return RifaiType.INT
        if isinstance(expr.value, float):
            return RifaiType.FLOAT
        if isinstance(expr.value, str):
            return RifaiType.STRING
        return RifaiType.ERROR

    def _analyze_variable_expr(self, expr: VariableExpression) -> RifaiType:
        symbol = self._symbol_table.resolve(expr.name)
        if symbol is None:
            self._error(expr.span, f"Undefined variable '{expr.name}'.")
            return RifaiType.ERROR
        if isinstance(symbol, FunctionSymbol):
            self._error(
                expr.span,
                f"Function '{expr.name}' cannot be used as a variable value.",
            )
            return RifaiType.ERROR

        self._variable_bindings[id(expr)] = symbol
        return symbol.rifai_type

    def _analyze_unary(self, expr: UnaryExpression) -> RifaiType:
        operand_type = self._analyze_expression(expr.operand)
        if is_error_type(operand_type):
            return RifaiType.ERROR

        op_type = expr.operator.token_type
        if op_type is TokenType.MINUS:
            if is_numeric(operand_type):
                return operand_type
            self._error(
                expr.span,
                f"Unary '-' requires 'int' or 'float', got '{operand_type.value}'.",
            )
            return RifaiType.ERROR

        if op_type is TokenType.NOT:
            if operand_type is RifaiType.BOOL:
                return RifaiType.BOOL
            self._error(
                expr.span,
                f"Unary 'not' requires 'bool', got '{operand_type.value}'.",
            )
            return RifaiType.ERROR

        return RifaiType.ERROR

    def _analyze_binary(self, expr: BinaryExpression) -> RifaiType:
        left = self._analyze_expression(expr.left)
        right = self._analyze_expression(expr.right)
        if is_error_type(left) or is_error_type(right):
            return RifaiType.ERROR

        op = expr.operator.token_type

        if op is TokenType.PLUS:
            if left is right and left in (
                RifaiType.INT,
                RifaiType.FLOAT,
                RifaiType.STRING,
            ):
                return left
            self._error(
                expr.span,
                f"Operator '+' is not supported for '{left.value}' and '{right.value}'.",
            )
            return RifaiType.ERROR

        if op in (TokenType.MINUS, TokenType.STAR):
            if left is right and is_numeric(left):
                return left
            self._error(
                expr.span,
                f"Operator '{expr.operator.lexeme}' is not supported for "
                f"'{left.value}' and '{right.value}'.",
            )
            return RifaiType.ERROR

        if op is TokenType.SLASH:
            if left is right and is_numeric(left):
                return RifaiType.FLOAT
            self._error(
                expr.span,
                f"Operator '/' is not supported for '{left.value}' and '{right.value}'.",
            )
            return RifaiType.ERROR

        if op is TokenType.MODULO:
            if left is RifaiType.INT and right is RifaiType.INT:
                return RifaiType.INT
            self._error(
                expr.span,
                f"Operator '%' requires 'int' operands, got '{left.value}' and '{right.value}'.",
            )
            return RifaiType.ERROR

        if op in _RELATIONAL_OPS:
            if left is right and is_numeric(left):
                return RifaiType.BOOL
            self._error(
                expr.span,
                f"Comparison '{expr.operator.lexeme}' requires matching numeric operands, "
                f"got '{left.value}' and '{right.value}'.",
            )
            return RifaiType.ERROR

        if op in _EQUALITY_OPS:
            if left is right and is_value_type(left):
                return RifaiType.BOOL
            self._error(
                expr.span,
                f"Equality '{expr.operator.lexeme}' is not supported for "
                f"'{left.value}' and '{right.value}'.",
            )
            return RifaiType.ERROR

        if op in (TokenType.AND, TokenType.OR):
            if left is RifaiType.BOOL and right is RifaiType.BOOL:
                return RifaiType.BOOL
            self._error(
                expr.span,
                f"Logical operator '{expr.operator.lexeme}' requires 'bool' operands, "
                f"got '{left.value}' and '{right.value}'.",
            )
            return RifaiType.ERROR

        return RifaiType.ERROR

    def _analyze_call(self, expr: FunctionCallExpression) -> RifaiType:
        arg_types = [self._analyze_expression(arg) for arg in expr.arguments]
        symbol = self._symbol_table.resolve(expr.callee)

        if symbol is None:
            self._error(
                SourceSpan.from_token(expr.callee_token),
                f"Undefined function '{expr.callee}'.",
            )
            return RifaiType.ERROR

        if not isinstance(symbol, FunctionSymbol):
            self._error(
                SourceSpan.from_token(expr.callee_token),
                f"'{expr.callee}' is a variable and cannot be called as a function.",
            )
            return RifaiType.ERROR

        self._function_bindings[id(expr)] = symbol

        if len(expr.arguments) != len(symbol.params):
            self._error(
                expr.span,
                f"Function '{expr.callee}' expects {len(symbol.params)} argument(s), "
                f"got {len(expr.arguments)}.",
            )
            return symbol.return_type

        for index, (arg_node, arg_type, param_sym) in enumerate(
            zip(expr.arguments, arg_types, symbol.params), start=1
        ):
            if (
                not is_error_type(arg_type)
                and not is_error_type(param_sym.rifai_type)
                and arg_type is not param_sym.rifai_type
            ):
                self._error(
                    arg_node.span,
                    f"Argument {index} ('{param_sym.name}') of function '{expr.callee}' "
                    f"expects '{param_sym.rifai_type.value}', got '{arg_type.value}'.",
                )

        return symbol.return_type

    # --- Control-flow return analysis ----------------------------------------

    def _definitely_returns(self, stmt: Statement) -> bool:
        if isinstance(stmt, ReturnStatement):
            return True
        if isinstance(stmt, BlockStatement):
            return any(self._definitely_returns(inner) for inner in stmt.statements)
        if isinstance(stmt, IfStatement):
            if stmt.else_branch is None:
                return False
            return self._definitely_returns(
                stmt.then_branch
            ) and self._definitely_returns(stmt.else_branch)
        return False
