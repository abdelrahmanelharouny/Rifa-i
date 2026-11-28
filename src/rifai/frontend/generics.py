"""Compile-time inference and monomorphization for generic Rifa'i functions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
import re

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
from rifai.frontend.ast_nodes import (
    ArrayLiteralExpression, AssignmentStatement, BinaryExpression, BlockStatement,
    BreakStatement, ContinueStatement, EnumConstructorExpression, EnumDeclaration,
    Expression, ExpressionStatement, ForStatement, FunctionCallExpression,
    FunctionDeclaration, GroupingExpression, IfStatement, IndexAssignmentStatement,
    IndexExpression, LiteralExpression, MatchExpression, MemberAssignmentStatement,
    MemberExpression, PrintStatement, Program, ReturnStatement, SourceSpan,
    Statement, StructDeclaration, TypeAnnotation, TypeApplicationExpression, UnaryExpression,
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
        self._generic_structs: dict[str, StructDeclaration] = {}
        self._generic_enums: dict[str, EnumDeclaration] = {}
        self._function_returns: dict[str, str] = {}
        self._structs: dict[str, StructDeclaration] = {}
        self._enums: dict[str, EnumDeclaration] = {}
        self._nominal_names: set[str] = set()
        self._specializations: dict[tuple[str, tuple[str, ...]], FunctionDeclaration] = {}
        self._specialization_positions: dict[tuple[str, tuple[str, ...]], int] = {}
        self._specialization_list: list[FunctionDeclaration] = []
        self._specialized_returns: dict[str, str] = {}
        self._reserved_names: set[str] = set()
        self._specialized_type_cache: dict[tuple[str, tuple[str, ...]], str] = {}
        self._specialized_type_positions: dict[tuple[str, tuple[str, ...]], int] = {}
        self._specialized_type_list: list[Statement] = []
        self._specialized_type_names: set[str] = set()
        self._type_descriptors: dict[str, tuple[str, tuple[str, ...], str]] = {}
        self._enum_type_names: set[str] = set()

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
                if declaration.type_parameters:
                    self._generic_structs[declaration.name] = declaration
            elif isinstance(declaration, EnumDeclaration):
                self._enums[declaration.name] = declaration
                self._nominal_names.add(declaration.name)
                self._enum_type_names.add(declaration.name)
                if declaration.type_parameters:
                    self._generic_enums[declaration.name] = declaration

        self._reserved_names = set(self._functions) | self._nominal_names
        for declaration in program.declarations:
            if isinstance(declaration, FunctionDeclaration) and declaration.type_parameters:
                self._generic_functions[declaration.name] = declaration
                self._validate_generic_declaration(declaration)
            elif isinstance(declaration, (StructDeclaration, EnumDeclaration)) and declaration.type_parameters:
                self._validate_generic_type_declaration(declaration)

        if self._diagnostics:
            return GenericSpecializationResult(program, tuple(self._diagnostics))

        globals_: dict[str, str] = {}
        rewritten: list[Statement] = []
        for declaration in program.declarations:
            if isinstance(declaration, FunctionDeclaration):
                if declaration.type_parameters:
                    continue
                rewritten.append(self._rewrite_function(declaration))
            elif isinstance(declaration, StructDeclaration):
                if declaration.type_parameters:
                    continue
                rewritten.append(self._rewrite_struct_declaration(declaration, {}))
            elif isinstance(declaration, EnumDeclaration):
                if declaration.type_parameters:
                    continue
                rewritten.append(self._rewrite_enum_declaration(declaration, {}))
            else:
                rewritten.append(self._rewrite_statement(declaration, globals_, {}))

        if self._diagnostics:
            return GenericSpecializationResult(program, tuple(self._diagnostics))
        expanded = replace(
            program,
            declarations=tuple([
                *rewritten,
                *self._specialized_type_list,
                *self._specialization_list,
            ]),
        )
        return GenericSpecializationResult(expanded, ())

    def _error(self, span: SourceSpan, message: str) -> None:
        self._diagnostics.append(Diagnostic(
            phase=DiagnosticPhase.SEMANTIC, message=message,
            line=span.line, column=span.column,
            start_offset=span.start_offset, end_offset=span.end_offset,
        ))

    _KNOWN_CONSTRAINTS = frozenset({
        "Numeric", "Integral", "Addable", "Comparable", "Ordered",
        "Equatable", "Display", "Printable", "ArrayElement", "Copy",
    })

    @staticmethod
    def _split_top_level_types(text: str) -> tuple[str, ...]:
        parts: list[str] = []
        depth_angle = 0
        depth_square = 0
        start = 0
        for index, character in enumerate(text):
            if character == "<":
                depth_angle += 1
            elif character == ">":
                depth_angle -= 1
            elif character == "[":
                depth_square += 1
            elif character == "]":
                depth_square -= 1
            elif character == "," and depth_angle == 0 and depth_square == 0:
                parts.append(text[start:index].strip())
                start = index + 1
        if start < len(text):
            parts.append(text[start:].strip())
        return tuple(item for item in parts if item)

    @classmethod
    def _parse_type_shape(cls, name: str) -> tuple[str, tuple[str, ...], int]:
        """Return base name, generic arguments, and trailing array rank."""
        rank = 0
        base = name
        while base.endswith("[]"):
            base = base[:-2]
            rank += 1
        opening = base.find("<")
        if opening < 0 or not base.endswith(">"):
            return base, (), rank
        root = base[:opening]
        arguments_text = base[opening + 1:-1]
        return root, cls._split_top_level_types(arguments_text), rank

    def _validate_type_parameters(
        self,
        owner: str,
        tokens: tuple[Token, ...],
        bounds: tuple[tuple[str, ...], ...],
    ) -> None:
        seen: set[str] = set()
        if bounds and len(bounds) != len(tokens):
            self._error(
                SourceSpan.from_token(tokens[0]) if tokens else SourceSpan(1, 1, 0, 0),
                f"Generic declaration '{owner}' has malformed type-parameter constraints.",
            )
        for index, token in enumerate(tokens):
            if token.lexeme in seen:
                self._error(SourceSpan.from_token(token),
                            f"Duplicate generic type parameter '{token.lexeme}' in '{owner}'.")
            seen.add(token.lexeme)
            if type_from_name(token.lexeme) is not None or token.lexeme in self._nominal_names:
                self._error(SourceSpan.from_token(token),
                            f"Generic type parameter '{token.lexeme}' shadows a declared type.")
            constraints = bounds[index] if index < len(bounds) else ()
            if len(set(constraints)) != len(constraints):
                self._error(SourceSpan.from_token(token),
                            f"Duplicate constraint on type parameter '{token.lexeme}'.")
            for constraint in constraints:
                if constraint not in self._KNOWN_CONSTRAINTS:
                    self._error(SourceSpan.from_token(token),
                                f"Unknown type constraint '{constraint}' on '{token.lexeme}'.")

    def _validate_generic_type_declaration(
        self, declaration: StructDeclaration | EnumDeclaration
    ) -> None:
        if declaration.name.startswith(_INTERNAL_PREFIX):
            self._error(SourceSpan.from_token(declaration.name_token),
                        f"Type names beginning with '{_INTERNAL_PREFIX}' are reserved.")
        self._validate_type_parameters(
            declaration.name, declaration.type_parameters, declaration.type_parameter_bounds
        )

    def _is_known_concrete_type(self, name: str) -> bool:
        base, arguments, rank = self._parse_type_shape(name)
        if rank:
            return self._is_known_concrete_type(base + (("<" + ",".join(arguments) + ">") if arguments else ""))
        if arguments:
            return base in self._generic_structs or base in self._generic_enums
        return (
            type_from_name(base) is not None
            or base in self._nominal_names
            or base in self._specialized_type_names
        )

    def _satisfies_constraint(self, type_name: str, constraint: str) -> bool:
        """Evaluate a built-in static capability against one concrete type."""
        base, arguments, rank = self._parse_type_shape(type_name)
        if rank:
            if constraint in {"Display", "Printable", "ArrayElement"}:
                return True
            if constraint == "Equatable":
                return True
            return False
        is_enum = base in self._enum_type_names or (
            base in self._type_descriptors and self._type_descriptors[base][2] == "enum"
        )
        is_struct = base in self._structs or (
            base in self._type_descriptors and self._type_descriptors[base][2] == "struct"
        )
        if constraint == "Numeric":
            return type_name in {"int", "float"}
        if constraint == "Integral":
            return type_name == "int"
        if constraint == "Addable":
            return type_name in {"int", "float", "string"}
        if constraint in {"Comparable", "Ordered"}:
            return type_name in {"int", "float"}
        if constraint == "Equatable":
            return type_name in {"int", "float", "bool", "string"} or is_enum
        if constraint in {"Display", "Printable"}:
            return type_name != "void" and self._is_known_concrete_type(type_name)
        if constraint == "ArrayElement":
            return type_name != "void" and self._is_known_concrete_type(type_name)
        if constraint == "Copy":
            return type_name in {"int", "float", "bool", "string"} or is_enum
        return False

    def _check_type_arguments(
        self,
        owner: str,
        tokens: tuple[Token, ...],
        bounds: tuple[tuple[str, ...], ...],
        arguments: tuple[str, ...],
        span: SourceSpan,
    ) -> bool:
        valid = True
        if len(arguments) != len(tokens):
            self._error(
                span,
                f"Generic type '{owner}' expects {len(tokens)} type argument(s), got {len(arguments)}.",
            )
            return False
        for index, argument in enumerate(arguments):
            if not self._is_known_concrete_type(argument) or argument == "void":
                self._error(span,
                            f"'{argument}' is not a valid concrete type argument for '{owner}'.")
                valid = False
                continue
            constraints = bounds[index] if index < len(bounds) else ()
            for constraint in constraints:
                if not self._satisfies_constraint(argument, constraint):
                    self._error(
                        span,
                        f"Type '{argument}' does not satisfy constraint '{constraint}' "
                        f"for parameter '{tokens[index].lexeme}' in '{owner}'.",
                    )
                    valid = False
        return valid

    def _specialize_type_name(
        self,
        name: str,
        span: SourceSpan,
        substitutions: dict[str, str],
    ) -> str:
        """Resolve type variables and create concrete nominal generic instances."""
        base, arguments, rank = self._parse_type_shape(name)
        if not base:
            return name
        if base in substitutions and not arguments:
            return substitutions[base] + "[]" * rank

        if arguments:
            concrete_arguments = tuple(
                self._specialize_type_name(item, span, substitutions)
                for item in arguments
            )
            if base in self._generic_structs or base in self._generic_enums:
                specialized = self._instantiate_generic_nominal(base, concrete_arguments, span)
                return (specialized or base) + "[]" * rank
            self._error(span, f"Type '{base}' is not a generic type and cannot accept type arguments.")
            return name

        if base in self._generic_structs or base in self._generic_enums:
            self._error(span,
                        f"Generic type '{base}' requires {len((self._generic_structs.get(base) or self._generic_enums[base]).type_parameters)} explicit type argument(s).")
            return name
        return base + "[]" * rank

    def _specialize_annotation(
        self,
        annotation: TypeAnnotation | None,
        substitutions: dict[str, str],
    ) -> TypeAnnotation | None:
        if annotation is None:
            return None
        specialized = self._specialize_type_name(annotation.name, annotation.span, substitutions)
        return replace(annotation, name=specialized) if specialized != annotation.name else annotation

    def _instantiate_generic_nominal(
        self,
        owner: str,
        arguments: tuple[str, ...],
        span: SourceSpan,
    ) -> str | None:
        template: StructDeclaration | EnumDeclaration | None = (
            self._generic_structs.get(owner) or self._generic_enums.get(owner)
        )
        if template is None:
            return None
        if not self._check_type_arguments(
            owner,
            template.type_parameters,
            template.type_parameter_bounds,
            arguments,
            span,
        ):
            return None
        key = (owner, arguments)
        cached = self._specialized_type_cache.get(key)
        if cached is not None:
            return cached

        digest = sha256("\0".join((owner, *arguments)).encode("utf-8")).hexdigest()[:10]
        generated_name = f"{_INTERNAL_PREFIX}type_{owner}_{digest}"
        if generated_name in self._reserved_names:
            self._error(span, f"Generated type name '{generated_name}' conflicts with a user declaration.")
            return None

        self._specialized_type_cache[key] = generated_name
        self._specialized_type_positions[key] = len(self._specialized_type_list)
        substitutions = {
            token.lexeme: argument
            for token, argument in zip(template.type_parameters, arguments)
        }
        self._type_descriptors[generated_name] = (
            owner, arguments, "struct" if isinstance(template, StructDeclaration) else "enum"
        )
        self._specialized_type_names.add(generated_name)

        generated_token = replace(template.name_token, lexeme=generated_name)
        if isinstance(template, StructDeclaration):
            placeholder: Statement = replace(
                template,
                name=generated_name,
                name_token=generated_token,
                fields=(),
                type_parameters=(),
                type_parameter_bounds=(),
            )
        else:
            placeholder = replace(
                template,
                name=generated_name,
                name_token=generated_token,
                variants=(),
                type_parameters=(),
                type_parameter_bounds=(),
            )
        self._specialized_type_list.append(placeholder)

        if isinstance(template, StructDeclaration):
            fields = tuple(
                replace(
                    field,
                    type_annotation=self._specialize_annotation(field.type_annotation, substitutions),
                )
                for field in deepcopy(template.fields)
            )
            specialized_decl = replace(placeholder, fields=fields)
            self._structs[generated_name] = specialized_decl
        else:
            variants = tuple(
                replace(
                    variant,
                    payload_types=tuple(
                        self._specialize_annotation(annotation, substitutions)
                        for annotation in variant.payload_types
                    ),
                )
                for variant in deepcopy(template.variants)
            )
            specialized_decl = replace(placeholder, variants=variants)
            self._enums[generated_name] = specialized_decl
            self._enum_type_names.add(generated_name)

        self._specialized_type_list[self._specialized_type_positions[key]] = specialized_decl
        return generated_name

    def _rewrite_struct_declaration(
        self, declaration: StructDeclaration, substitutions: dict[str, str]
    ) -> StructDeclaration:
        return replace(
            declaration,
            fields=tuple(
                replace(field, type_annotation=self._specialize_annotation(field.type_annotation, substitutions))
                for field in declaration.fields
            ),
        )

    def _rewrite_enum_declaration(
        self, declaration: EnumDeclaration, substitutions: dict[str, str]
    ) -> EnumDeclaration:
        return replace(
            declaration,
            variants=tuple(
                replace(
                    variant,
                    payload_types=tuple(
                        self._specialize_annotation(annotation, substitutions)
                        for annotation in variant.payload_types
                    ),
                )
                for variant in declaration.variants
            ),
        )

    def _validate_generic_declaration(self, function: FunctionDeclaration) -> None:
        if function.name.startswith(_INTERNAL_PREFIX):
            self._error(SourceSpan.from_token(function.name_token),
                        f"Function names beginning with '{_INTERNAL_PREFIX}' are reserved.")
        if function.name in BUILTIN_FUNCTIONS or function.name in self._nominal_names:
            self._error(SourceSpan.from_token(function.name_token),
                        f"Generic function name '{function.name}' conflicts with a reserved name.")
        self._validate_type_parameters(
            function.name, function.type_parameters, function.type_parameter_bounds
        )
        names = {item.lexeme for item in function.type_parameters}
        inferable = {
            token.lexeme
            for token in function.type_parameters
            if any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(token.lexeme)}(?![A-Za-z0-9_])",
                             parameter.type_annotation.name)
                   for parameter in function.params)
        }
        for missing in names - inferable:
            token = next(item for item in function.type_parameters if item.lexeme == missing)
            self._error(
                SourceSpan.from_token(token),
                f"Generic type parameter '{missing}' must appear in a parameter type so it can be inferred."
            )

    def _rewrite_function(self, function: FunctionDeclaration) -> FunctionDeclaration:
        params = tuple(
            replace(parameter, type_annotation=self._specialize_annotation(parameter.type_annotation, {}))
            for parameter in function.params
        )
        return_type = self._specialize_annotation(function.return_type, {})
        env = {p.name: p.type_annotation.name for p in params}
        body = self._rewrite_block(function.body, env, {})
        self._function_returns[function.name] = return_type.name
        return replace(function, params=params, return_type=return_type, body=body)

    def _rewrite_block(self, block: BlockStatement, env: dict[str, str],
                       substitutions: dict[str, str]) -> BlockStatement:
        local = dict(env)
        statements = tuple(self._rewrite_statement(s, local, substitutions) for s in block.statements)
        return replace(block, statements=statements) if statements != block.statements else block

    def _rewrite_statement(self, stmt: Statement, env: dict[str, str],
                           substitutions: dict[str, str]) -> Statement:
        if isinstance(stmt, VariableDeclaration):
            init = self._rewrite_expression(stmt.initializer, env, substitutions)
            annotation = self._specialize_annotation(stmt.type_annotation, substitutions)
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

    def _unify_type_pattern(
        self,
        pattern: str,
        actual: str,
        typevars: set[str],
        substitutions: dict[str, str],
        span: SourceSpan,
        owner: str,
    ) -> bool:
        """Unify one generic type expression with its inferred concrete type."""
        pbase, pargs, prank = self._parse_type_shape(pattern)
        abase, aargs, arank = self._parse_type_shape(actual)

        if pbase in typevars and not pargs:
            if arank < prank:
                self._error(span,
                            f"Generic parameter '{pattern}' in '{owner}' requires a compatible array type, got '{actual}'.")
                return False
            inferred = actual[:len(actual) - 2 * prank] if prank else actual
            previous = substitutions.get(pbase)
            if previous is not None and previous != inferred:
                self._error(span,
                            f"Conflicting inferences for '{pbase}' in '{owner}': '{previous}' and '{inferred}'.")
                return False
            substitutions[pbase] = inferred
            return True

        if prank != arank:
            return True  # The ordinary semantic checker reports non-generic type mismatches.

        if pbase in self._generic_structs or pbase in self._generic_enums:
            descriptor = self._type_descriptors.get(abase)
            if descriptor is None:
                return True
            actual_owner, actual_arguments, _kind = descriptor
            if actual_owner != pbase or len(pargs) != len(actual_arguments):
                return True
            for left, right in zip(pargs, actual_arguments):
                self._unify_type_pattern(left, right, typevars, substitutions, span, owner)
            return True

        if pargs:
            if abase == pbase and len(pargs) == len(aargs):
                for left, right in zip(pargs, aargs):
                    self._unify_type_pattern(left, right, typevars, substitutions, span, owner)
                return True
            return True

        expected = self._specialize_type_name(pattern, span, substitutions)
        return expected == actual

    def _infer_generic_type_arguments(
        self,
        owner: str,
        tokens: tuple[Token, ...],
        bounds: tuple[tuple[str, ...], ...],
        type_patterns: tuple[str, ...],
        arguments: tuple[Expression, ...],
        env: dict[str, str],
        explicit: tuple[TypeAnnotation, ...],
        span: SourceSpan,
    ) -> tuple[str, ...] | None:
        if explicit and len(explicit) != len(tokens):
            self._error(
                span,
                f"Generic declaration '{owner}' expects {len(tokens)} explicit type argument(s), got {len(explicit)}.",
            )
            return None
        substitutions: dict[str, str] = {}
        if explicit:
            for token, annotation in zip(tokens, explicit):
                substitutions[token.lexeme] = self._specialize_type_name(
                    annotation.name, annotation.span, {}
                )

        typevars = {item.lexeme for item in tokens}
        for index, (pattern, argument) in enumerate(zip(type_patterns, arguments)):
            actual = self._infer_expression_type(argument, env)
            if actual is None:
                if any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(item)}(?![A-Za-z0-9_])", pattern)
                       for item in typevars - substitutions.keys()):
                    variable = next(
                        item for item in tokens
                        if item.lexeme not in substitutions
                        and re.search(rf"(?<![A-Za-z0-9_]){re.escape(item.lexeme)}(?![A-Za-z0-9_])", pattern)
                    )
                    self._error(
                        argument.span,
                        f"Cannot infer generic type parameter '{variable.lexeme}' for '{owner}' "
                        f"from argument {index + 1}; use a value with a concrete type or provide explicit type arguments.",
                    )
                continue
            self._unify_type_pattern(pattern, actual, typevars, substitutions, argument.span, owner)

        missing = typevars - substitutions.keys()
        if missing:
            token = next(item for item in tokens if item.lexeme == sorted(missing)[0])
            self._error(
                span,
                f"Cannot infer generic type parameter '{token.lexeme}' for '{owner}'. "
                "Provide explicit type arguments when inference is ambiguous.",
            )
            return None
        concrete = tuple(substitutions[item.lexeme] for item in tokens)
        if not self._check_type_arguments(owner, tokens, bounds, concrete, span):
            return None
        return concrete

    def _rewrite_expression(
        self,
        expr: Expression,
        env: dict[str, str],
        substitutions: dict[str, str],
    ) -> Expression:
        if isinstance(expr, FunctionCallExpression):
            args = tuple(self._rewrite_expression(a, env, substitutions) for a in expr.arguments)
            rewritten = replace(expr, arguments=args) if args != expr.arguments else expr

            struct_template = self._generic_structs.get(expr.callee)
            if struct_template is not None:
                patterns = tuple(item.type_annotation.name for item in struct_template.fields)
                concrete = self._infer_generic_type_arguments(
                    struct_template.name,
                    struct_template.type_parameters,
                    struct_template.type_parameter_bounds,
                    patterns,
                    args,
                    env,
                    expr.type_arguments,
                    expr.span,
                )
                if concrete is None:
                    return rewritten
                generated = self._instantiate_generic_nominal(expr.callee, concrete, expr.span)
                if generated is None:
                    return rewritten
                return replace(
                    rewritten,
                    callee=generated,
                    callee_token=replace(expr.callee_token, lexeme=generated),
                    type_arguments=(),
                )
            template = self._generic_functions.get(expr.callee)
            if template is not None:
                name = self._specialize_call(template, args, env, expr.type_arguments, expr.span)
                if name is None:
                    return rewritten
                return replace(
                    rewritten,
                    callee=name,
                    callee_token=replace(expr.callee_token, lexeme=name),
                    type_arguments=(),
                )
            if expr.type_arguments:
                self._error(expr.span,
                            f"Function or type '{expr.callee}' does not accept explicit type arguments.")
            return rewritten

        if isinstance(expr, TypeApplicationExpression):
            type_text = expr.name + "<" + ",".join(item.name for item in expr.type_arguments) + ">"
            specialized = self._specialize_type_name(type_text, expr.span, substitutions)
            token = replace(expr.name_token, lexeme=specialized)
            return VariableExpression(name=specialized, token=token, span=expr.span)

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
            if isinstance(obj, VariableExpression) and obj.name in self._generic_enums:
                self._error(expr.span,
                            f"Generic enum variant '{obj.name}.{expr.name}' requires explicit type arguments, e.g. {obj.name}<int>.{expr.name}.")
            return replace(expr, object=obj) if obj is not expr.object else expr
        if isinstance(expr, EnumConstructorExpression):
            args = tuple(self._rewrite_expression(a, env, substitutions) for a in expr.arguments)
            template = self._generic_enums.get(expr.enum_name)
            if template is not None:
                variant = next((item for item in template.variants if item.name == expr.variant_name), None)
                if variant is None:
                    return replace(expr, arguments=args) if args != expr.arguments else expr
                patterns = tuple(item.name for item in variant.payload_types)
                concrete = self._infer_generic_type_arguments(
                    template.name,
                    template.type_parameters,
                    template.type_parameter_bounds,
                    patterns,
                    args,
                    env,
                    expr.type_arguments,
                    expr.span,
                )
                if concrete is None:
                    return replace(expr, arguments=args) if args != expr.arguments else expr
                generated = self._instantiate_generic_nominal(expr.enum_name, concrete, expr.span)
                if generated is None:
                    return replace(expr, arguments=args) if args != expr.arguments else expr
                return replace(
                    expr,
                    enum_name=generated,
                    enum_token=replace(expr.enum_token, lexeme=generated),
                    arguments=args,
                    type_arguments=(),
                )
            if expr.type_arguments:
                self._error(expr.span,
                            f"Enum '{expr.enum_name}' is not generic and cannot accept type arguments.")
            return replace(expr, arguments=args) if args != expr.arguments else expr

        if isinstance(expr, MatchExpression):
            subject = self._rewrite_expression(expr.subject, env, substitutions)
            subject_type = self._infer_expression_type(subject, env)
            subject_descriptor = self._type_descriptors.get(subject_type) if subject_type else None
            enum_owner = subject_type
            enum_args: tuple[str, ...] = ()
            if subject_descriptor is not None and subject_descriptor[2] == "enum":
                enum_owner, enum_args, _ = subject_descriptor
            enum_decl = self._enums.get(subject_type) if subject_type else None
            arms = []
            for arm in expr.arms:
                local = dict(env)
                rewritten_arm = arm
                if not arm.wildcard:
                    pattern_enum = arm.enum_name or ""
                    if pattern_enum in self._generic_enums:
                        if arm.type_arguments:
                            concrete = tuple(
                                self._specialize_type_name(item.name, item.span, substitutions)
                                for item in arm.type_arguments
                            )
                        elif subject_descriptor is not None and subject_descriptor[0] == pattern_enum:
                            concrete = enum_args
                        else:
                            self._error(
                                arm.span,
                                f"Pattern for generic enum '{pattern_enum}' must specify type arguments "
                                "or match the concrete enum type of its subject.",
                            )
                            concrete = ()
                        if concrete:
                            generated = self._instantiate_generic_nominal(pattern_enum, concrete, arm.span)
                            if generated is not None:
                                rewritten_arm = replace(arm, enum_name=generated, type_arguments=())
                    elif arm.type_arguments:
                        self._error(arm.span, f"Enum '{pattern_enum}' is not generic and cannot accept type arguments.")
                selected_enum = self._enums.get(rewritten_arm.enum_name or "")
                if selected_enum is not None and not rewritten_arm.wildcard:
                    variant = next((v for v in selected_enum.variants if v.name == rewritten_arm.variant_name), None)
                    if variant is not None:
                        for token, annotation in zip(rewritten_arm.bindings, variant.payload_types):
                            local[token.lexeme] = annotation.name
                body = self._rewrite_expression(arm.body, local, substitutions)
                arms.append(replace(rewritten_arm, body=body) if body is not rewritten_arm.body else rewritten_arm)
            arms = tuple(arms)
            return replace(expr, subject=subject, arms=arms) if (subject, arms) != (expr.subject, expr.arms) else expr
        return expr

    def _specialize_call(
        self,
        template: FunctionDeclaration,
        args: tuple[Expression, ...],
        env: dict[str, str],
        explicit_type_arguments: tuple[TypeAnnotation, ...] = (),
        call_span: SourceSpan | None = None,
    ) -> str | None:
        span = call_span or template.span
        if len(args) != len(template.params):
            self._error(span,
                        f"Generic function '{template.name}' expects {len(template.params)} argument(s), got {len(args)}.")
            return None
        patterns = tuple(item.type_annotation.name for item in template.params)
        concrete = self._infer_generic_type_arguments(
            template.name,
            template.type_parameters,
            template.type_parameter_bounds,
            patterns,
            args,
            env,
            explicit_type_arguments,
            span,
        )
        if concrete is None:
            return None
        key = (template.name, concrete)
        cached = self._specializations.get(key)
        if cached is not None:
            return cached.name
        digest = sha256("\0".join(concrete).encode("utf-8")).hexdigest()[:10]
        name = f"{_INTERNAL_PREFIX}{template.name}_{digest}"
        if name in self._reserved_names:
            self._error(span,
                        f"Generated specialization name '{name}' conflicts with a user declaration.")
            return None

        substitutions = {
            token.lexeme: value
            for token, value in zip(template.type_parameters, concrete)
        }
        params = tuple(
            replace(parameter, type_annotation=self._specialize_annotation(parameter.type_annotation, substitutions))
            for parameter in template.params
        )
        return_type = self._specialize_annotation(template.return_type, substitutions)
        placeholder = replace(
            template,
            name=name,
            name_token=replace(template.name_token, lexeme=name),
            params=params,
            return_type=return_type,
            body=replace(template.body, statements=()),
            type_parameters=(),
            type_parameter_bounds=(),
        )
        self._specializations[key] = placeholder
        self._specialization_positions[key] = len(self._specialization_list)
        self._specialization_list.append(placeholder)
        self._specialized_returns[name] = return_type.name

        local_env = {parameter.name: parameter.type_annotation.name for parameter in params}
        body = self._rewrite_block(deepcopy(template.body), local_env, substitutions)
        specialized = replace(placeholder, body=body)
        self._specializations[key] = specialized
        self._specialization_list[self._specialization_positions[key]] = specialized
        return name

    def _substitute_type_name(self, name: str, substitutions: dict[str, str]) -> str:
        return self._specialize_type_name(name, SourceSpan(1, 1, 0, 0), substitutions)

    def _substitute_annotation(self, annotation: TypeAnnotation | None,
                               substitutions: dict[str, str]) -> TypeAnnotation | None:
        return self._specialize_annotation(annotation, substitutions)

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
            return types[0] + "[]"
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
