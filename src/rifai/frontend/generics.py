"""Compile-time inference and monomorphization for generic Rifa'i functions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import (
    ArrayLiteralExpression, AssignmentStatement, BinaryExpression, BlockStatement,
    BreakStatement, ContinueStatement, EnumConstructorExpression, EnumDeclaration,
    Expression, ExpressionStatement, ForStatement, FunctionCallExpression,
    FunctionDeclaration, GroupingExpression, IfStatement, IndexAssignmentStatement,
    IndexExpression, LiteralExpression, MatchExpression, MemberAssignmentStatement,
    MemberExpression, PrintStatement, Program, ReturnStatement, SourceSpan,
    Statement, StructDeclaration, TypeAnnotation, UnaryExpression,
    VariableDeclaration, VariableExpression, WhileStatement,
)
from rifai.frontend.tokens import Token
from rifai.frontend.types import type_from_name
from rifai.stdlib import BUILTIN_FUNCTIONS

_INTERNAL_PREFIX = "__rifai_generic_"


@dataclass(frozen=True, slots=True)
class GenericSpecializationResult:
    program: Program
    diagnostics: tuple[Diagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


class GenericSpecializer:
    """Infer type arguments and expand generic functions into ordinary functions.

    Type variables are inferred from function arguments. The existing semantic
    analyzer, typed IR, bytecode verifier, and VM therefore operate only on
    concrete, statically typed function instances.
    """

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []
        self._functions: dict[str, FunctionDeclaration] = {}
        self._generic_functions: dict[str, FunctionDeclaration] = {}
        self._function_returns: dict[str, str] = {}
        self._structs: dict[str, StructDeclaration] = {}
        self._enums: dict[str, EnumDeclaration] = {}
        self._nominal_names: set[str] = set()
        self._specializations: dict[tuple[str, tuple[str, ...]], FunctionDeclaration] = {}
        self._specialization_positions: dict[tuple[str, tuple[str, ...]], int] = {}
        self._specialization_list: list[FunctionDeclaration] = []
        self._specialized_returns: dict[str, str] = {}
        self._reserved_names: set[str] = set()

    def specialize(self, program: Program) -> GenericSpecializationResult:
        self.__init__()
        for declaration in program.declarations:
            if isinstance(declaration, FunctionDeclaration):
                if declaration.name in self._functions:
                    previous = self._functions[declaration.name]
                    if declaration.type_parameters or previous.type_parameters:
                        self._error(SourceSpan.from_token(declaration.name_token),
                                    f"Generic function '{declaration.name}' cannot be overloaded.")
                else:
                    self._functions[declaration.name] = declaration
                self._function_returns[declaration.name] = declaration.return_type.name
            elif isinstance(declaration, StructDeclaration):
                self._structs[declaration.name] = declaration
                self._nominal_names.add(declaration.name)
            elif isinstance(declaration, EnumDeclaration):
                self._enums[declaration.name] = declaration
                self._nominal_names.add(declaration.name)

        self._reserved_names = set(self._functions) | self._nominal_names
        for declaration in program.declarations:
            if isinstance(declaration, FunctionDeclaration) and declaration.type_parameters:
                self._generic_functions[declaration.name] = declaration
                self._validate_generic_declaration(declaration)

        if self._diagnostics:
            return GenericSpecializationResult(program, tuple(self._diagnostics))

        globals_: dict[str, str] = {}
        rewritten: list[Statement] = []
        for declaration in program.declarations:
            if isinstance(declaration, FunctionDeclaration):
                if declaration.type_parameters:
                    continue
                rewritten.append(self._rewrite_function(declaration))
            elif isinstance(declaration, Statement):
                rewritten.append(self._rewrite_statement(declaration, globals_, {}))
            else:
                rewritten.append(declaration)

        if self._diagnostics:
            return GenericSpecializationResult(program, tuple(self._diagnostics))
        expanded = replace(program, declarations=tuple([*rewritten, *self._specialization_list]))
        return GenericSpecializationResult(expanded, ())

    def _error(self, span: SourceSpan, message: str) -> None:
        self._diagnostics.append(Diagnostic(
            phase=DiagnosticPhase.SEMANTIC, message=message,
            line=span.line, column=span.column,
            start_offset=span.start_offset, end_offset=span.end_offset,
        ))

    def _validate_generic_declaration(self, function: FunctionDeclaration) -> None:
        if function.name.startswith(_INTERNAL_PREFIX):
            self._error(SourceSpan.from_token(function.name_token),
                        f"Function names beginning with '{_INTERNAL_PREFIX}' are reserved.")
        if function.name in BUILTIN_FUNCTIONS or function.name in self._nominal_names:
            self._error(SourceSpan.from_token(function.name_token),
                        f"Generic function name '{function.name}' conflicts with a reserved name.")
        names: set[str] = set()
        for token in function.type_parameters:
            if token.lexeme in names:
                self._error(SourceSpan.from_token(token),
                            f"Duplicate generic type parameter '{token.lexeme}'.")
            if type_from_name(token.lexeme) is not None or token.lexeme in self._nominal_names:
                self._error(SourceSpan.from_token(token),
                            f"Generic type parameter '{token.lexeme}' shadows a declared type.")
            names.add(token.lexeme)
        inferable: set[str] = set()
        for parameter in function.params:
            pattern = parameter.type_annotation.name
            if pattern in names:
                inferable.add(pattern)
            elif pattern.endswith("[]") and pattern[:-2] in names:
                inferable.add(pattern[:-2])
        for missing in names - inferable:
            token = next(item for item in function.type_parameters if item.lexeme == missing)
            self._error(SourceSpan.from_token(token),
                        f"Generic type parameter '{missing}' must appear in a parameter type so it can be inferred.")

    def _rewrite_function(self, function: FunctionDeclaration) -> FunctionDeclaration:
        env = {p.name: p.type_annotation.name for p in function.params}
        body = self._rewrite_block(function.body, env, {})
        return replace(function, body=body) if body is not function.body else function

    def _rewrite_block(self, block: BlockStatement, env: dict[str, str],
                       substitutions: dict[str, str]) -> BlockStatement:
        local = dict(env)
        statements = tuple(self._rewrite_statement(s, local, substitutions) for s in block.statements)
        return replace(block, statements=statements) if statements != block.statements else block

    def _rewrite_statement(self, stmt: Statement, env: dict[str, str],
                           substitutions: dict[str, str]) -> Statement:
        if isinstance(stmt, VariableDeclaration):
            init = self._rewrite_expression(stmt.initializer, env, substitutions)
            annotation = self._substitute_annotation(stmt.type_annotation, substitutions)
            inferred = annotation.name if annotation else self._infer_expression_type(init, env)
            if inferred is not None:
                env[stmt.name] = inferred
            return replace(stmt, initializer=init, type_annotation=annotation) if (
                init is not stmt.initializer or annotation is not stmt.type_annotation
            ) else stmt
        if isinstance(stmt, AssignmentStatement):
            value = self._rewrite_expression(stmt.value, env, substitutions)
            return replace(stmt, value=value) if value is not stmt.value else stmt
        if isinstance(stmt, IndexAssignmentStatement):
            array = self._rewrite_expression(stmt.array, env, substitutions)
            index = self._rewrite_expression(stmt.index, env, substitutions)
            value = self._rewrite_expression(stmt.value, env, substitutions)
            return replace(stmt, array=array, index=index, value=value) if (
                (array, index, value) != (stmt.array, stmt.index, stmt.value)
            ) else stmt
        if isinstance(stmt, MemberAssignmentStatement):
            obj = self._rewrite_expression(stmt.object, env, substitutions)
            value = self._rewrite_expression(stmt.value, env, substitutions)
            return replace(stmt, object=obj, value=value) if (obj, value) != (stmt.object, stmt.value) else stmt
        if isinstance(stmt, BlockStatement):
            return self._rewrite_block(stmt, env, substitutions)
        if isinstance(stmt, IfStatement):
            condition = self._rewrite_expression(stmt.condition, env, substitutions)
            then = self._rewrite_block(stmt.then_branch, env, substitutions)
            other = stmt.else_branch
            if isinstance(other, BlockStatement):
                other = self._rewrite_block(other, env, substitutions)
            elif isinstance(other, IfStatement):
                other = self._rewrite_statement(other, dict(env), substitutions)
            return replace(stmt, condition=condition, then_branch=then, else_branch=other) if (
                (condition, then, other) != (stmt.condition, stmt.then_branch, stmt.else_branch)
            ) else stmt
        if isinstance(stmt, WhileStatement):
            condition = self._rewrite_expression(stmt.condition, env, substitutions)
            body = self._rewrite_block(stmt.body, env, substitutions)
            return replace(stmt, condition=condition, body=body) if (
                (condition, body) != (stmt.condition, stmt.body)
            ) else stmt
        if isinstance(stmt, ForStatement):
            local = dict(env)
            init = self._rewrite_statement(stmt.initializer, local, substitutions) if stmt.initializer else None
            condition = self._rewrite_expression(stmt.condition, local, substitutions) if stmt.condition else None
            increment = self._rewrite_statement(stmt.increment, local, substitutions) if stmt.increment else None
            body = self._rewrite_block(stmt.body, local, substitutions)
            values = (init, condition, increment, body)
            old = (stmt.initializer, stmt.condition, stmt.increment, stmt.body)
            return replace(stmt, initializer=init, condition=condition, increment=increment, body=body) if values != old else stmt
        if isinstance(stmt, ReturnStatement) and stmt.value is not None:
            value = self._rewrite_expression(stmt.value, env, substitutions)
            return replace(stmt, value=value) if value is not stmt.value else stmt
        if isinstance(stmt, PrintStatement):
            value = self._rewrite_expression(stmt.expression, env, substitutions)
            return replace(stmt, expression=value) if value is not stmt.expression else stmt
        if isinstance(stmt, ExpressionStatement):
            value = self._rewrite_expression(stmt.expression, env, substitutions)
            return replace(stmt, expression=value) if value is not stmt.expression else stmt
        if isinstance(stmt, (BreakStatement, ContinueStatement)):
            return stmt
        return stmt

    def _rewrite_expression(self, expr: Expression, env: dict[str, str],
                            substitutions: dict[str, str]) -> Expression:
        if isinstance(expr, FunctionCallExpression):
            args = tuple(self._rewrite_expression(a, env, substitutions) for a in expr.arguments)
            rewritten = replace(expr, arguments=args) if args != expr.arguments else expr
            template = self._generic_functions.get(expr.callee)
            if template is None:
                return rewritten
            name = self._specialize_call(template, args, env)
            if name is None:
                return rewritten
            return replace(rewritten, callee=name,
                           callee_token=replace(expr.callee_token, lexeme=name))
        if isinstance(expr, UnaryExpression):
            value = self._rewrite_expression(expr.operand, env, substitutions)
            return replace(expr, operand=value) if value is not expr.operand else expr
        if isinstance(expr, BinaryExpression):
            left = self._rewrite_expression(expr.left, env, substitutions)
            right = self._rewrite_expression(expr.right, env, substitutions)
            return replace(expr, left=left, right=right) if (left, right) != (expr.left, expr.right) else expr
        if isinstance(expr, GroupingExpression):
            value = self._rewrite_expression(expr.expression, env, substitutions)
            return replace(expr, expression=value) if value is not expr.expression else expr
        if isinstance(expr, ArrayLiteralExpression):
            items = tuple(self._rewrite_expression(x, env, substitutions) for x in expr.elements)
            return replace(expr, elements=items) if items != expr.elements else expr
        if isinstance(expr, IndexExpression):
            array = self._rewrite_expression(expr.array, env, substitutions)
            index = self._rewrite_expression(expr.index, env, substitutions)
            return replace(expr, array=array, index=index) if (array, index) != (expr.array, expr.index) else expr
        if isinstance(expr, MemberExpression):
            obj = self._rewrite_expression(expr.object, env, substitutions)
            return replace(expr, object=obj) if obj is not expr.object else expr
        if isinstance(expr, EnumConstructorExpression):
            args = tuple(self._rewrite_expression(a, env, substitutions) for a in expr.arguments)
            return replace(expr, arguments=args) if args != expr.arguments else expr
        if isinstance(expr, MatchExpression):
            subject = self._rewrite_expression(expr.subject, env, substitutions)
            subject_type = self._infer_expression_type(subject, env)
            enum_decl = self._enums.get(subject_type) if subject_type else None
            arms = []
            for arm in expr.arms:
                local = dict(env)
                if enum_decl is not None and not arm.wildcard:
                    variant = next((v for v in enum_decl.variants if v.name == arm.variant_name), None)
                    if variant is not None:
                        for token, annotation in zip(arm.bindings, variant.payload_types):
                            local[token.lexeme] = self._substitute_type_name(annotation.name, substitutions)
                body = self._rewrite_expression(arm.body, local, substitutions)
                arms.append(replace(arm, body=body) if body is not arm.body else arm)
            arms = tuple(arms)
            return replace(expr, subject=subject, arms=arms) if (subject, arms) != (expr.subject, expr.arms) else expr
        return expr

    def _specialize_call(self, template: FunctionDeclaration, args: tuple[Expression, ...],
                         env: dict[str, str]) -> str | None:
        if len(args) != len(template.params):
            self._error(template.span,
                        f"Generic function '{template.name}' expects {len(template.params)} argument(s), got {len(args)}.")
            return None
        typevars = {token.lexeme for token in template.type_parameters}
        substitutions: dict[str, str] = {}
        for index, (parameter, argument) in enumerate(zip(template.params, args)):
            pattern = parameter.type_annotation.name
            variable = pattern[:-2] if pattern.endswith("[]") and pattern[:-2] in typevars else pattern
            if variable not in typevars:
                continue
            actual = self._infer_expression_type(argument, env)
            if actual is None:
                self._error(argument.span,
                            f"Cannot infer generic type parameter '{variable}' for '{template.name}' from argument {index + 1}; pass a value with a concrete type.")
                return None
            inferred = actual
            if pattern.endswith("[]"):
                if not actual.endswith("[]"):
                    self._error(argument.span,
                                f"Generic parameter '{variable}[]' in '{template.name}' requires an array argument, got '{actual}'.")
                    return None
                inferred = actual[:-2]
                if inferred.endswith("[]"):
                    self._error(argument.span, "Nested arrays are not supported by Rifa'i generic specialization.")
                    return None
            previous = substitutions.get(variable)
            if previous is not None and previous != inferred:
                self._error(argument.span,
                            f"Conflicting inferences for '{variable}' in '{template.name}': '{previous}' and '{inferred}'.")
                return None
            substitutions[variable] = inferred

        missing = typevars - substitutions.keys()
        if missing:
            missing_name = sorted(missing)[0]
            self._error(SourceSpan.from_token(template.name_token),
                        f"Cannot infer generic type parameter '{missing_name}' for '{template.name}' from its parameters.")
            return None
        concrete = tuple(substitutions[token.lexeme] for token in template.type_parameters)
        for name in concrete:
            if name == "void" or (type_from_name(name) is None and name not in self._nominal_names):
                self._error(SourceSpan.from_token(template.name_token),
                            f"Generic function '{template.name}' cannot be specialized with unknown or invalid type '{name}'.")
                return None

        key = (template.name, concrete)
        cached = self._specializations.get(key)
        if cached is not None:
            return cached.name
        digest = sha256("\0".join(concrete).encode("utf-8")).hexdigest()[:10]
        name = f"{_INTERNAL_PREFIX}{template.name}_{digest}"
        if name in self._reserved_names:
            self._error(SourceSpan.from_token(template.name_token),
                        f"Generated specialization name '{name}' conflicts with a user declaration.")
            return None

        params = tuple(replace(p, type_annotation=self._substitute_annotation(p.type_annotation, substitutions))
                       for p in template.params)
        return_type = self._substitute_annotation(template.return_type, substitutions)
        placeholder = replace(
            template, name=name, name_token=replace(template.name_token, lexeme=name),
            params=params, return_type=return_type,
            body=replace(template.body, statements=()), type_parameters=(),
        )
        self._specializations[key] = placeholder
        self._specialization_positions[key] = len(self._specialization_list)
        self._specialization_list.append(placeholder)
        self._specialized_returns[name] = return_type.name

        local_env = {p.name: p.type_annotation.name for p in params}
        # Each concrete instantiation must own distinct AST node identities.
        # SemanticResult stores bindings by id(node), so shared source nodes
        # between specializations would allow one instance to overwrite another.
        body = self._rewrite_block(deepcopy(template.body), local_env, substitutions)
        specialized = replace(placeholder, body=body)
        self._specializations[key] = specialized
        self._specialization_list[self._specialization_positions[key]] = specialized
        return name

    @staticmethod
    def _substitute_type_name(name: str, substitutions: dict[str, str]) -> str:
        if name in substitutions:
            return substitutions[name]
        if name.endswith("[]") and name[:-2] in substitutions:
            return substitutions[name[:-2]] + "[]"
        return name

    def _substitute_annotation(self, annotation: TypeAnnotation | None,
                                substitutions: dict[str, str]) -> TypeAnnotation | None:
        if annotation is None:
            return None
        name = self._substitute_type_name(annotation.name, substitutions)
        return replace(annotation, name=name) if name != annotation.name else annotation

    def _infer_expression_type(self, expr: Expression, env: dict[str, str]) -> str | None:
        if isinstance(expr, LiteralExpression):
            if isinstance(expr.value, bool): return "bool"
            if isinstance(expr.value, int): return "int"
            if isinstance(expr.value, float): return "float"
            if isinstance(expr.value, str): return "string"
        if isinstance(expr, VariableExpression):
            return env.get(expr.name)
        if isinstance(expr, GroupingExpression):
            return self._infer_expression_type(expr.expression, env)
        if isinstance(expr, ArrayLiteralExpression):
            if not expr.elements: return None
            types = [self._infer_expression_type(item, env) for item in expr.elements]
            if any(item is None for item in types) or len(set(types)) != 1: return None
            return types[0] + "[]" if types[0] in {"int", "float", "bool", "string"} else None
        if isinstance(expr, EnumConstructorExpression):
            return expr.enum_name
        if isinstance(expr, MemberExpression):
            if isinstance(expr.object, VariableExpression) and expr.object.name in self._enums:
                return expr.object.name
            object_type = self._infer_expression_type(expr.object, env)
            declaration = self._structs.get(object_type) if object_type else None
            field = next((x for x in declaration.fields if x.name == expr.name), None) if declaration else None
            return field.type_annotation.name if field else None
        if isinstance(expr, IndexExpression):
            array_type = self._infer_expression_type(expr.array, env)
            return array_type[:-2] if array_type and array_type.endswith("[]") else None
        if isinstance(expr, UnaryExpression):
            return self._infer_expression_type(expr.operand, env)
        if isinstance(expr, BinaryExpression):
            left = self._infer_expression_type(expr.left, env)
            right = self._infer_expression_type(expr.right, env)
            if left is None or left != right: return None
            op = expr.operator.lexeme
            if op in {"==", "!=", "<", ">", "<=", ">=", "and", "or"}: return "bool"
            if op == "/": return "float"
            return left
        if isinstance(expr, MatchExpression):
            return self._infer_expression_type(expr.arms[0].body, env) if expr.arms else None
        if isinstance(expr, FunctionCallExpression):
            if expr.callee in self._specialized_returns: return self._specialized_returns[expr.callee]
            if expr.callee in self._structs: return expr.callee
            if expr.callee in self._function_returns: return self._function_returns[expr.callee]
            args = expr.arguments
            if expr.callee == "len": return "int"
            if expr.callee == "push": return "void"
            if expr.callee == "pop" and args:
                array = self._infer_expression_type(args[0], env)
                return array[:-2] if array and array.endswith("[]") else None
            if expr.callee in {"abs", "min", "max"} and args:
                return self._infer_expression_type(args[0], env)
            if expr.callee == "sqrt": return "float"
            if expr.callee in {"round", "to_int"}: return "int"
            if expr.callee == "to_float": return "float"
            if expr.callee in {"to_string", "substring", "read_text"}: return "string"
            if expr.callee in {"contains", "starts_with", "ends_with", "file_exists", "write_text"}: return "bool"
        return None
