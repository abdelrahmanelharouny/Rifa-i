"""Semantic analyzer and static type checker for the Rifa'i language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.stdlib import BUILTIN_FUNCTIONS
from rifai.frontend.ast_nodes import (
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
    ImportDeclaration,
    StructDeclaration,
    StructField,
    EnumDeclaration,
    EnumVariant,
    EnumConstructorExpression,
    MatchArm,
    MatchExpression,
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
    ForStatement,
    BreakStatement,
    ContinueStatement,
)
from rifai.frontend.symbol_table import FunctionSymbol, SymbolTable, VariableSymbol
from rifai.frontend.tokens import TokenType
from rifai.frontend.types import (
    ArrayType,
    RifaiType,
    StaticType,
    UserDefinedType,
    array_element_type,
    array_type_for,
    is_array_type,
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

_BUILTIN_FUNCTIONS: Final[frozenset[str]] = frozenset(BUILTIN_FUNCTIONS)

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
    expression_types: dict[int, StaticType]
    variable_bindings: dict[int, VariableSymbol]
    function_bindings: dict[int, FunctionSymbol]
    global_symbols: dict[str, VariableSymbol | FunctionSymbol]
    struct_declarations: dict[str, StructDeclaration]
    enum_declarations: dict[str, EnumDeclaration]
    constructor_bindings: dict[int, StructDeclaration]
    member_bindings: dict[int, StructField]
    enum_variant_bindings: dict[int, tuple[str, str]]
    enum_constructor_bindings: dict[int, tuple[EnumDeclaration, EnumVariant]]
    match_variant_bindings: dict[int, EnumVariant]
    pattern_bindings: dict[int, tuple[VariableSymbol, ...]]

    @property
    def is_valid(self) -> bool:
        """Return True when semantic analysis completed with zero diagnostics."""
        return len(self.diagnostics) == 0

    def type_of(self, expression: Expression) -> StaticType | None:
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
        self._expression_types: dict[int, StaticType] = {}
        self._variable_bindings: dict[int, VariableSymbol] = {}
        self._function_bindings: dict[int, FunctionSymbol] = {}
        self._current_function: FunctionSymbol | None = None
        self._struct_declarations: dict[str, StructDeclaration] = {}
        self._enum_declarations: dict[str, EnumDeclaration] = {}
        self._nominal_types: dict[str, UserDefinedType] = {}
        self._constructor_bindings: dict[int, StructDeclaration] = {}
        self._member_bindings: dict[int, StructField] = {}
        self._enum_variant_bindings: dict[int, tuple[str, str]] = {}
        self._enum_constructor_bindings: dict[int, tuple[EnumDeclaration, EnumVariant]] = {}
        self._match_variant_bindings: dict[int, EnumVariant] = {}
        self._pattern_bindings: dict[int, tuple[VariableSymbol, ...]] = {}
        self._loop_depth = 0

    def analyze(self, program: Program) -> SemanticResult:
        """Analyze a parsed Rifa'i Program AST and return a SemanticResult."""
        self._symbol_table = SymbolTable()
        self._diagnostics = []
        self._expression_types = {}
        self._variable_bindings = {}
        self._function_bindings = {}
        self._current_function = None
        self._struct_declarations = {}
        self._enum_declarations = {}
        self._nominal_types = {}
        self._constructor_bindings = {}
        self._member_bindings = {}
        self._enum_variant_bindings = {}
        self._enum_constructor_bindings = {}
        self._match_variant_bindings = {}
        self._pattern_bindings = {}
        self._loop_depth = 0

        self._collect_type_declarations(program)
        for struct in self._struct_declarations.values():
            for field in struct.fields:
                field_type = self._resolve_type(field.type_annotation.name)
                if field_type is None or field_type is RifaiType.VOID:
                    self._error(field.type_annotation.span,
                                f"Unknown or invalid field type '{field.type_annotation.name}'.")
        for enum in self._enum_declarations.values():
            for variant in enum.variants:
                for payload_type in variant.payload_types:
                    resolved = self._resolve_type(payload_type.name)
                    if resolved is None or resolved is RifaiType.VOID:
                        self._error(payload_type.span,
                                    f"Unknown or invalid payload type '{payload_type.name}'.")
        self._collect_function_signatures(program)

        for decl in program.declarations:
            if isinstance(decl, FunctionDeclaration):
                self._analyze_function_declaration(decl)
            elif isinstance(decl, (StructDeclaration, EnumDeclaration, ImportDeclaration)):
                continue
            else:
                self._analyze_statement(decl)

        return SemanticResult(
            diagnostics=tuple(self._diagnostics),
            expression_types=dict(self._expression_types),
            variable_bindings=dict(self._variable_bindings),
            function_bindings=dict(self._function_bindings),
            global_symbols=self._symbol_table.global_scope.symbols,
            struct_declarations=dict(self._struct_declarations),
            enum_declarations=dict(self._enum_declarations),
            constructor_bindings=dict(self._constructor_bindings),
            member_bindings=dict(self._member_bindings),
            enum_variant_bindings=dict(self._enum_variant_bindings),
            enum_constructor_bindings=dict(self._enum_constructor_bindings),
            match_variant_bindings=dict(self._match_variant_bindings),
            pattern_bindings=dict(self._pattern_bindings),
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

    def _collect_type_declarations(self, program: Program) -> None:
        """Register all nominal types before resolving any function signatures."""
        for declaration in program.declarations:
            if isinstance(declaration, StructDeclaration):
                name = declaration.name
                if name in self._nominal_types or type_from_name(name) is not None or name in _BUILTIN_FUNCTIONS:
                    self._error(SourceSpan.from_token(declaration.name_token),
                                f"Duplicate or reserved type name '{name}'.")
                    continue
                if not declaration.fields:
                    self._error(declaration.span, f"Struct '{name}' must declare at least one field.")
                    continue
                seen: set[str] = set()
                for item in declaration.fields:
                    if item.name in seen:
                        self._error(SourceSpan.from_token(item.name_token),
                                    f"Duplicate field '{item.name}' in struct '{name}'.")
                    seen.add(item.name)
                self._struct_declarations[name] = declaration
                self._nominal_types[name] = UserDefinedType(name, "struct")
            elif isinstance(declaration, EnumDeclaration):
                name = declaration.name
                if name in self._nominal_types or type_from_name(name) is not None or name in _BUILTIN_FUNCTIONS:
                    self._error(SourceSpan.from_token(declaration.name_token),
                                f"Duplicate or reserved type name '{name}'.")
                    continue
                seen_variants: set[str] = set()
                for variant in declaration.variants:
                    if variant.name in seen_variants:
                        self._error(SourceSpan.from_token(variant.name_token),
                                    f"Duplicate variant '{variant.name}' in enum '{name}'.")
                    seen_variants.add(variant.name)
                if not declaration.variants:
                    self._error(declaration.span, f"Enum '{name}' must declare at least one variant.")
                self._enum_declarations[name] = declaration
                self._nominal_types[name] = UserDefinedType(name, "enum")

    def _resolve_type(self, name: str) -> StaticType | None:
        resolved = type_from_name(name)
        if resolved is not None:
            return resolved
        if name.endswith("[]"):
            element = self._resolve_type(name[:-2])
            if element is not None and element not in (RifaiType.VOID, RifaiType.ERROR):
                return ArrayType(element)
        return self._nominal_types.get(name)

    # --- Pass 1: Function signature collection -------------------------------

    def _collect_function_signatures(self, program: Program) -> None:
        for decl in program.declarations:
            if not isinstance(decl, FunctionDeclaration):
                continue

            return_type = self._resolve_type(decl.return_type.name)
            if return_type is None:
                self._error(
                    decl.return_type.span,
                    f"Unknown return type '{decl.return_type.name}'.",
                )
                return_type = RifaiType.ERROR

            params: list[VariableSymbol] = []
            seen_params: set[str] = set()
            for param in decl.params:
                if param.name in _BUILTIN_FUNCTIONS:
                    self._error(
                        SourceSpan.from_token(param.name_token),
                        f"'{param.name}' is a reserved standard-library function name.",
                    )
                param_type = self._resolve_type(param.type_annotation.name)
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

            if decl.name in self._nominal_types:
                self._error(SourceSpan.from_token(decl.name_token),
                            f"Function name '{decl.name}' conflicts with a declared type.")
                continue

            if decl.name in _BUILTIN_FUNCTIONS:
                self._error(
                    SourceSpan.from_token(decl.name_token),
                    f"'{decl.name}' is a reserved standard-library function name.",
                )
                continue

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
        previous_loop_depth = self._loop_depth
        self._current_function = func_symbol
        self._loop_depth = 0
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
            self._loop_depth = previous_loop_depth

    def _analyze_statement(self, stmt: Statement) -> None:
        if isinstance(stmt, VariableDeclaration):
            self._analyze_variable_declaration(stmt)
        elif isinstance(stmt, AssignmentStatement):
            self._analyze_assignment(stmt)
        elif isinstance(stmt, IndexAssignmentStatement):
            self._analyze_index_assignment(stmt)
        elif isinstance(stmt, MemberAssignmentStatement):
            self._analyze_member_assignment(stmt)
        elif isinstance(stmt, BlockStatement):
            self._analyze_block(stmt)
        elif isinstance(stmt, IfStatement):
            self._analyze_if(stmt)
        elif isinstance(stmt, WhileStatement):
            self._analyze_while(stmt)
        elif isinstance(stmt, ForStatement):
            self._analyze_for(stmt)
        elif isinstance(stmt, BreakStatement):
            if self._loop_depth == 0:
                self._error(stmt.span, "'break' is only allowed inside a loop.")
        elif isinstance(stmt, ContinueStatement):
            if self._loop_depth == 0:
                self._error(stmt.span, "'continue' is only allowed inside a loop.")
        elif isinstance(stmt, ReturnStatement):
            self._analyze_return(stmt)
        elif isinstance(stmt, PrintStatement):
            self._analyze_print(stmt)
        elif isinstance(stmt, ExpressionStatement):
            self._analyze_expression(stmt.expression)
        elif isinstance(stmt, FunctionDeclaration):
            self._error(stmt.span, "Nested function declarations are not allowed.")

    def _analyze_variable_declaration(self, stmt: VariableDeclaration) -> None:
        declared_type = (
            self._resolve_type(stmt.type_annotation.name)
            if stmt.type_annotation is not None
            else None
        )
        if stmt.type_annotation is not None and declared_type is None:
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

        if stmt.name in self._nominal_types:
            self._error(
                SourceSpan.from_token(stmt.name_token),
                f"Variable name '{stmt.name}' conflicts with a declared type.",
            )

        if stmt.name in _BUILTIN_FUNCTIONS:
            self._error(
                SourceSpan.from_token(stmt.name_token),
                f"'{stmt.name}' is a reserved standard-library function name.",
            )

        init_type = self._analyze_expression(
            stmt.initializer,
            expected_type=declared_type if declared_type is not None and is_array_type(declared_type) else None,
        )
        if declared_type is None:
            declared_type = init_type
        if (
            not is_error_type(declared_type)
            and not is_error_type(init_type)
            and init_type != declared_type
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
        value_type = self._analyze_expression(
            stmt.value,
            expected_type=symbol.rifai_type if is_array_type(symbol.rifai_type) else None,
        )
        if (
            not is_error_type(symbol.rifai_type)
            and not is_error_type(value_type)
            and value_type != symbol.rifai_type
        ):
            self._error(
                stmt.value.span,
                f"Cannot assign value of type '{value_type.value}' to variable "
                f"'{stmt.name}' of type '{symbol.rifai_type.value}'.",
            )

    def _analyze_index_assignment(self, stmt: IndexAssignmentStatement) -> None:
        array_type = self._analyze_expression(stmt.array)
        index_type = self._analyze_expression(stmt.index)
        element_type = array_element_type(array_type)
        if element_type is None and not is_error_type(array_type):
            self._error(
                stmt.array.span,
                f"Indexed assignment requires an array, got '{array_type.value}'.",
            )
        if not is_error_type(index_type) and index_type is not RifaiType.INT:
            self._error(
                stmt.index.span,
                f"Array index must have type 'int', got '{index_type.value}'.",
            )
        value_type = self._analyze_expression(
            stmt.value,
            expected_type=element_type,
        )
        if (
            element_type is not None
            and not is_error_type(value_type)
            and value_type != element_type
        ):
            self._error(
                stmt.value.span,
                f"Array element expects '{element_type.value}', got '{value_type.value}'.",
            )

    def _analyze_member_assignment(self, stmt: MemberAssignmentStatement) -> None:
        member_type = self._member_type(stmt.object, stmt.name, stmt.name_token, id(stmt))
        value_type = self._analyze_expression(stmt.value)
        if not is_error_type(member_type) and not is_error_type(value_type) and member_type != value_type:
            self._error(stmt.value.span,
                        f"Field '{stmt.name}' expects '{member_type.value}', got '{value_type.value}'.")

    def _member_type(
        self,
        object_expression: Expression,
        member_name: str,
        member_token,
        binding_key: int,
    ) -> StaticType:
        object_type = self._analyze_expression(object_expression)
        if isinstance(object_type, UserDefinedType) and object_type.kind == "struct":
            declaration = self._struct_declarations.get(object_type.name)
            field = next((item for item in declaration.fields if item.name == member_name), None) if declaration else None
            if field is None:
                self._error(SourceSpan.from_token(member_token),
                            f"Struct '{object_type.name}' has no field '{member_name}'.")
                return RifaiType.ERROR
            self._member_bindings[binding_key] = field
            result = self._resolve_type(field.type_annotation.name)
            return result or RifaiType.ERROR
        self._error(SourceSpan.from_token(member_token),
                    f"Field access requires a struct value, got '{object_type.value}'.")
        return RifaiType.ERROR

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
        self._loop_depth += 1
        try:
            self._analyze_block(stmt.body)
        finally:
            self._loop_depth -= 1

    def _analyze_for(self, stmt: ForStatement) -> None:
        """Analyze for clauses and body in a dedicated loop scope."""
        self._symbol_table.enter_scope("for")
        try:
            if stmt.initializer is not None:
                self._analyze_statement(stmt.initializer)
            if stmt.condition is not None:
                cond_type = self._analyze_expression(stmt.condition)
                if not is_error_type(cond_type) and cond_type is not RifaiType.BOOL:
                    self._error(
                        stmt.condition.span,
                        f"'for' condition must have type 'bool', got '{cond_type.value}'.",
                    )
            if stmt.increment is not None:
                self._analyze_statement(stmt.increment)
            self._loop_depth += 1
            try:
                self._analyze_block(stmt.body)
            finally:
                self._loop_depth -= 1
        finally:
            self._symbol_table.exit_scope()

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

        actual = self._analyze_expression(
            stmt.value,
            expected_type=expected if is_array_type(expected) else None,
        )
        if (
            not is_error_type(expected)
            and not is_error_type(actual)
            and actual != expected
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

    def _analyze_expression(
        self,
        expr: Expression,
        *,
        expected_type: StaticType | None = None,
    ) -> RifaiType:
        result_type: RifaiType

        if isinstance(expr, LiteralExpression):
            result_type = self._type_of_literal(expr)
        elif isinstance(expr, VariableExpression):
            result_type = self._analyze_variable_expr(expr)
        elif isinstance(expr, GroupingExpression):
            result_type = self._analyze_expression(
                expr.expression,
                expected_type=expected_type,
            )
        elif isinstance(expr, ArrayLiteralExpression):
            result_type = self._analyze_array_literal(expr, expected_type)
        elif isinstance(expr, IndexExpression):
            array_type = self._analyze_expression(expr.array)
            index_type = self._analyze_expression(expr.index)
            element_type = array_element_type(array_type)
            if element_type is None and not is_error_type(array_type):
                self._error(
                    expr.array.span,
                    f"Indexing requires an array, got '{array_type.value}'.",
                )
            if not is_error_type(index_type) and index_type is not RifaiType.INT:
                self._error(
                    expr.index.span,
                    f"Array index must have type 'int', got '{index_type.value}'.",
                )
            result_type = element_type or RifaiType.ERROR
        elif isinstance(expr, MemberExpression):
            if (
                isinstance(expr.object, VariableExpression)
                and expr.object.name in self._enum_declarations
            ):
                declaration = self._enum_declarations[expr.object.name]
                variant = next((item for item in declaration.variants if item.name == expr.name), None)
                if variant is None:
                    self._error(SourceSpan.from_token(expr.name_token),
                                f"Enum '{declaration.name}' has no variant '{expr.name}'.")
                    result_type = RifaiType.ERROR
                elif variant.payload_types:
                    self._error(SourceSpan.from_token(expr.name_token),
                                f"Enum variant '{declaration.name}.{expr.name}' requires {len(variant.payload_types)} payload value(s).")
                    result_type = RifaiType.ERROR
                else:
                    self._enum_variant_bindings[id(expr)] = (declaration.name, expr.name)
                    result_type = self._nominal_types[declaration.name]
            else:
                result_type = self._member_type(
                    expr.object, expr.name, expr.name_token, id(expr)
                )
        elif isinstance(expr, EnumConstructorExpression):
            result_type = self._analyze_enum_constructor(expr)
        elif isinstance(expr, MatchExpression):
            result_type = self._analyze_match_expression(expr)
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

    def _analyze_enum_constructor(self, expr: EnumConstructorExpression) -> StaticType:
        declaration = self._enum_declarations.get(expr.enum_name)
        if declaration is None:
            self._error(SourceSpan.from_token(expr.enum_token), f"Unknown enum '{expr.enum_name}'.")
            for argument in expr.arguments:
                self._analyze_expression(argument)
            return RifaiType.ERROR
        variant = next((item for item in declaration.variants if item.name == expr.variant_name), None)
        if variant is None:
            self._error(SourceSpan.from_token(expr.variant_token),
                        f"Enum '{expr.enum_name}' has no variant '{expr.variant_name}'.")
            for argument in expr.arguments:
                self._analyze_expression(argument)
            return RifaiType.ERROR
        if len(expr.arguments) != len(variant.payload_types):
            self._error(expr.span,
                        f"Enum variant '{expr.enum_name}.{expr.variant_name}' expects {len(variant.payload_types)} payload value(s), got {len(expr.arguments)}.")
        for index, argument in enumerate(expr.arguments):
            actual = self._analyze_expression(argument)
            if index < len(variant.payload_types):
                expected = self._resolve_type(variant.payload_types[index].name)
                if expected is not None and not is_error_type(actual) and actual != expected:
                    self._error(argument.span,
                                f"Payload {index + 1} of '{expr.enum_name}.{expr.variant_name}' expects '{expected.value}', got '{actual.value}'.")
        self._enum_constructor_bindings[id(expr)] = (declaration, variant)
        return self._nominal_types[declaration.name]

    def _analyze_match_expression(self, expr: MatchExpression) -> StaticType:
        subject_type = self._analyze_expression(expr.subject)
        if not isinstance(subject_type, UserDefinedType) or subject_type.kind != "enum":
            self._error(expr.subject.span,
                        f"'match' requires an enum value, got '{subject_type.value}'.")
            for arm in expr.arms:
                self._analyze_expression(arm.body)
            return RifaiType.ERROR

        declaration = self._enum_declarations.get(subject_type.name)
        if declaration is None:
            self._error(expr.subject.span, f"Unknown enum type '{subject_type.name}'.")
            return RifaiType.ERROR

        seen_variants: set[str] = set()
        wildcard_seen = False
        result_type: StaticType | None = None
        for arm_index, arm in enumerate(expr.arms):
            if wildcard_seen:
                self._error(arm.span, "A wildcard match arm must be the final arm.")
            self._symbol_table.enter_scope("match-arm")
            try:
                if arm.wildcard:
                    if wildcard_seen:
                        self._error(arm.span, "A match expression can contain only one wildcard arm.")
                    wildcard_seen = True
                    if arm.bindings:
                        self._error(arm.span, "A wildcard pattern cannot bind enum payload values.")
                else:
                    if arm.enum_name != declaration.name:
                        self._error(
                            arm.enum_token and SourceSpan.from_token(arm.enum_token) or arm.span,
                            f"Pattern enum '{arm.enum_name}' does not match subject enum '{declaration.name}'.",
                        )
                    variant = next((item for item in declaration.variants if item.name == arm.variant_name), None)
                    if variant is None:
                        self._error(arm.variant_token and SourceSpan.from_token(arm.variant_token) or arm.span,
                                    f"Enum '{declaration.name}' has no variant '{arm.variant_name}'.")
                    else:
                        if variant.name in seen_variants:
                            self._error(arm.span, f"Duplicate match arm for '{declaration.name}.{variant.name}'.")
                        seen_variants.add(variant.name)
                        self._match_variant_bindings[id(arm)] = variant
                        if len(arm.bindings) != len(variant.payload_types):
                            self._error(arm.span,
                                f"Pattern '{declaration.name}.{variant.name}' expects {len(variant.payload_types)} binding(s), got {len(arm.bindings)}.")
                        symbols: list[VariableSymbol] = []
                        for index, token in enumerate(arm.bindings):
                            if index >= len(variant.payload_types):
                                break
                            payload_type = self._resolve_type(variant.payload_types[index].name) or RifaiType.ERROR
                            symbol = VariableSymbol(
                                name=token.lexeme,
                                rifai_type=payload_type,
                                declaration_span=SourceSpan.from_token(token),
                                is_parameter=False,
                                is_global=False,
                                scope_depth=self._symbol_table.current_scope.depth,
                            )
                            if not self._symbol_table.define_variable(symbol):
                                self._error(SourceSpan.from_token(token),
                                            f"Duplicate payload binding '{token.lexeme}' in match arm.")
                            else:
                                symbols.append(symbol)
                        self._pattern_bindings[id(arm)] = tuple(symbols)
                body_type = self._analyze_expression(arm.body)
            finally:
                self._symbol_table.exit_scope()
            if body_type is RifaiType.VOID:
                self._error(arm.body.span, "A match arm must produce a non-void value.")
            if result_type is None:
                result_type = body_type
            elif not is_error_type(body_type) and body_type != result_type:
                self._error(arm.body.span,
                            f"Match arm type mismatch: expected '{result_type.value}', got '{body_type.value}'.")

        all_variants = {item.name for item in declaration.variants}
        missing = sorted(all_variants - seen_variants)
        if missing and not wildcard_seen:
            self._error(expr.span,
                        "Non-exhaustive match; missing variant(s): " + ", ".join(missing) + ".")
        return result_type or RifaiType.ERROR

    def _analyze_array_literal(
        self,
        expr: ArrayLiteralExpression,
        expected_type: StaticType | None,
    ) -> StaticType:
        if not expr.elements:
            if expected_type is not None and is_array_type(expected_type):
                return expected_type
            self._error(
                expr.span,
                "An empty array literal requires an explicit array type annotation.",
            )
            return RifaiType.ERROR

        element_types = [self._analyze_expression(item) for item in expr.elements]
        first_type = element_types[0]
        inferred_array = (
            array_type_for(first_type)
            if not is_error_type(first_type) and first_type is not RifaiType.VOID
            else None
        )
        if inferred_array is None:
            self._error(
                expr.elements[0].span,
                f"Array elements must be values, got '{first_type.value}'.",
            )
            return RifaiType.ERROR

        result_type = expected_type if expected_type is not None and is_array_type(expected_type) else inferred_array
        expected_element = array_element_type(result_type)
        if expected_type is not None and not is_error_type(expected_type) and not is_array_type(expected_type):
            self._error(
                expr.span,
                f"Array literal cannot initialize a value of type '{expected_type.value}'.",
            )
        for item, actual_type in zip(expr.elements, element_types):
            if (
                expected_element is not None
                and not is_error_type(actual_type)
                and actual_type != expected_element
            ):
                self._error(
                    item.span,
                    f"Array elements must all have type '{expected_element.value}', got '{actual_type.value}'.",
                )
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

    def _analyze_call(self, expr: FunctionCallExpression) -> StaticType:
        struct = self._struct_declarations.get(expr.callee)
        if struct is not None:
            if len(expr.arguments) != len(struct.fields):
                self._error(
                    expr.span,
                    f"Struct '{expr.callee}' expects {len(struct.fields)} field value(s), got {len(expr.arguments)}.",
                )
            for index, argument in enumerate(expr.arguments):
                actual = self._analyze_expression(argument)
                if index < len(struct.fields):
                    expected = self._resolve_type(struct.fields[index].type_annotation.name)
                    if expected is not None and not is_error_type(actual) and actual != expected:
                        self._error(
                            argument.span,
                            f"Field '{struct.fields[index].name}' expects '{expected.value}', got '{actual.value}'.",
                        )
            self._constructor_bindings[id(expr)] = struct
            return self._nominal_types[struct.name]

        if expr.callee in {
            "abs", "min", "max", "sqrt", "round", "to_int", "to_float",
            "to_string", "contains", "starts_with", "ends_with", "substring",
            "read_text", "write_text", "file_exists",
        }:
            return self._analyze_standard_library_call(expr)
        if expr.callee == "len":
            argument_types = [
                self._analyze_expression(arg) for arg in expr.arguments
            ]
            if len(expr.arguments) != 1:
                self._error(expr.span, "'len' expects exactly one argument.")
                return RifaiType.ERROR
            argument_type = argument_types[0]
            if argument_type is RifaiType.STRING or is_array_type(argument_type):
                return RifaiType.INT
            if not is_error_type(argument_type):
                self._error(
                    expr.arguments[0].span,
                    f"'len' expects a string or array, got '{argument_type.value}'.",
                )
            return RifaiType.ERROR

        if expr.callee == "push":
            argument_types = [
                self._analyze_expression(arg) for arg in expr.arguments
            ]
            if len(expr.arguments) != 2:
                self._error(expr.span, "'push' expects an array and one element value.")
                return RifaiType.ERROR
            element_type = array_element_type(argument_types[0])
            if element_type is None:
                if not is_error_type(argument_types[0]):
                    self._error(
                        expr.arguments[0].span,
                        f"'push' expects an array as its first argument, got '{argument_types[0].value}'.",
                    )
                return RifaiType.ERROR
            if (
                not is_error_type(argument_types[1])
                and argument_types[1] != element_type
            ):
                self._error(
                    expr.arguments[1].span,
                    f"'push' expects an element of type '{element_type.value}', got '{argument_types[1].value}'.",
                )
            return RifaiType.VOID

        if expr.callee == "pop":
            argument_types = [
                self._analyze_expression(arg) for arg in expr.arguments
            ]
            if len(expr.arguments) != 1:
                self._error(expr.span, "'pop' expects exactly one array argument.")
                return RifaiType.ERROR
            element_type = array_element_type(argument_types[0])
            if element_type is None:
                if not is_error_type(argument_types[0]):
                    self._error(
                        expr.arguments[0].span,
                        f"'pop' expects an array, got '{argument_types[0].value}'.",
                    )
                return RifaiType.ERROR
            return element_type

        symbol = self._symbol_table.resolve(expr.callee)
        if symbol is None:
            self._error(
                SourceSpan.from_token(expr.callee_token),
                f"Undefined function '{expr.callee}'.",
            )
            for argument in expr.arguments:
                self._analyze_expression(argument)
            return RifaiType.ERROR

        if not isinstance(symbol, FunctionSymbol):
            self._error(
                SourceSpan.from_token(expr.callee_token),
                f"'{expr.callee}' is a variable and cannot be called as a function.",
            )
            for argument in expr.arguments:
                self._analyze_expression(argument)
            return RifaiType.ERROR

        self._function_bindings[id(expr)] = symbol
        if len(expr.arguments) != len(symbol.params):
            self._error(
                expr.span,
                f"Function '{expr.callee}' expects {len(symbol.params)} argument(s), "
                f"got {len(expr.arguments)}.",
            )

        for index, arg_node in enumerate(expr.arguments):
            expected = (
                symbol.params[index].rifai_type
                if index < len(symbol.params)
                else None
            )
            arg_type = self._analyze_expression(
                arg_node,
                expected_type=expected if is_array_type(expected) else None,
            )
            if (
                expected is not None
                and not is_error_type(arg_type)
                and not is_error_type(expected)
                and arg_type != expected
            ):
                self._error(
                    arg_node.span,
                    f"Argument {index + 1} of function '{expr.callee}' "
                    f"expects '{expected.value}', got '{arg_type.value}'.",
                )
        return symbol.return_type

    def _analyze_standard_library_call(self, expr: FunctionCallExpression) -> StaticType:
        name = expr.callee
        arguments = [self._analyze_expression(item) for item in expr.arguments]

        def arity(expected: int) -> bool:
            if len(arguments) != expected:
                self._error(expr.span, f"'{name}' expects {expected} argument(s), got {len(arguments)}.")
                return False
            return True

        def require(index: int, accepted: tuple[StaticType, ...], description: str) -> bool:
            if index >= len(arguments) or is_error_type(arguments[index]):
                return False
            if arguments[index] not in accepted:
                self._error(
                    expr.arguments[index].span,
                    f"'{name}' expects {description}, got '{arguments[index].value}'.",
                )
                return False
            return True

        numeric = (RifaiType.INT, RifaiType.FLOAT)
        if name == "abs":
            if not arity(1):
                return RifaiType.ERROR
            return arguments[0] if require(0, numeric, "an int or float") else RifaiType.ERROR
        if name in ("min", "max"):
            if not arity(2):
                return RifaiType.ERROR
            ok = require(0, numeric, "matching numeric values") and require(1, numeric, "matching numeric values")
            if ok and arguments[0] != arguments[1]:
                self._error(expr.span, f"'{name}' arguments must have the same numeric type.")
                ok = False
            return arguments[0] if ok else RifaiType.ERROR
        if name == "sqrt":
            if not arity(1):
                return RifaiType.ERROR
            return RifaiType.FLOAT if require(0, numeric, "an int or float") else RifaiType.ERROR
        if name == "round":
            if not arity(1):
                return RifaiType.ERROR
            return RifaiType.INT if require(0, numeric, "an int or float") else RifaiType.ERROR
        if name == "to_int":
            if not arity(1):
                return RifaiType.ERROR
            return RifaiType.INT if require(0, numeric, "an int or float") else RifaiType.ERROR
        if name == "to_float":
            if not arity(1):
                return RifaiType.ERROR
            return RifaiType.FLOAT if require(0, numeric, "an int or float") else RifaiType.ERROR
        if name == "to_string":
            if not arity(1):
                return RifaiType.ERROR
            if arguments[0] is RifaiType.VOID:
                self._error(expr.arguments[0].span, "'to_string' cannot convert void.")
                return RifaiType.ERROR
            return RifaiType.STRING
        if name in ("contains", "starts_with", "ends_with"):
            if not arity(2):
                return RifaiType.ERROR
            ok = require(0, (RifaiType.STRING,), "a string") and require(1, (RifaiType.STRING,), "a string")
            return RifaiType.BOOL if ok else RifaiType.ERROR
        if name == "substring":
            if not arity(3):
                return RifaiType.ERROR
            ok = (
                require(0, (RifaiType.STRING,), "a string")
                and require(1, (RifaiType.INT,), "an integer start index")
                and require(2, (RifaiType.INT,), "an integer end index")
            )
            return RifaiType.STRING if ok else RifaiType.ERROR
        if name in ("read_text", "file_exists"):
            if not arity(1):
                return RifaiType.ERROR
            if not require(0, (RifaiType.STRING,), "a relative path string"):
                return RifaiType.ERROR
            return RifaiType.STRING if name == "read_text" else RifaiType.BOOL
        if name == "write_text":
            if not arity(2):
                return RifaiType.ERROR
            ok = require(0, (RifaiType.STRING,), "a relative path string")
            ok = require(1, (RifaiType.STRING,), "text content") and ok
            return RifaiType.BOOL if ok else RifaiType.ERROR
        return RifaiType.ERROR

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
