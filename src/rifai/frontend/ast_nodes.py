"""Abstract Syntax Tree (AST) node definitions and formatter for Rifa'i."""

from __future__ import annotations

from dataclasses import dataclass

from rifai.frontend.tokens import Token


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Source location span covering one or more tokens."""

    line: int
    column: int
    start_offset: int
    end_offset: int

    @classmethod
    def from_token(cls, token: Token) -> SourceSpan:
        """Create a span from a single token."""
        return cls(
            line=token.line,
            column=token.column,
            start_offset=token.start_offset,
            end_offset=token.end_offset,
        )

    @classmethod
    def between(cls, start: Token | SourceSpan, end: Token | SourceSpan) -> SourceSpan:
        """Create a span covering from `start` through `end`."""
        return cls(
            line=start.line,
            column=start.column,
            start_offset=start.start_offset,
            end_offset=end.end_offset,
        )


class ASTNode:
    """Base marker class for all Rifa'i AST nodes."""


class Statement(ASTNode):
    """Base marker class for all Rifa'i statement and declaration nodes."""


class Expression(ASTNode):
    """Base marker class for all Rifa'i expression nodes."""


@dataclass(frozen=True, slots=True)
class TypeAnnotation(ASTNode):
    """Explicit type annotation in variable declarations, parameters, and returns."""

    name: str
    token: Token
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Parameter(ASTNode):
    """Typed parameter in a function declaration."""

    name: str
    name_token: Token
    type_annotation: TypeAnnotation
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Program(ASTNode):
    """Root AST node representing an entire Rifa'i translation unit."""

    declarations: tuple[Statement, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ImportDeclaration(Statement):
    """A relative source-module import, resolved by the compiler."""

    path: str
    path_token: Token
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class StructField(ASTNode):
    """One named, statically typed field in a struct declaration."""

    name: str
    name_token: Token
    type_annotation: TypeAnnotation
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class StructDeclaration(Statement):
    """Nominal record type with an ordered field schema."""

    name: str
    name_token: Token
    fields: tuple[StructField, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EnumDeclaration(Statement):
    """Nominal enum with a finite set of unit variants."""

    name: str
    name_token: Token
    variants: tuple[Token, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BlockStatement(Statement):
    """Lexically scoped sequence of statements enclosed in braces."""

    statements: tuple[Statement, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class FunctionDeclaration(Statement):
    """Top-level function declaration."""

    name: str
    name_token: Token
    params: tuple[Parameter, ...]
    return_type: TypeAnnotation
    body: BlockStatement
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class VariableDeclaration(Statement):
    """Typed variable declaration with mandatory initializer."""

    name: str
    name_token: Token
    type_annotation: TypeAnnotation | None
    initializer: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class AssignmentStatement(Statement):
    """Variable reassignment statement."""

    name: str
    name_token: Token
    value: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IndexAssignmentStatement(Statement):
    """Assignment to one element of a typed array."""

    array: Expression
    index: Expression
    value: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class MemberAssignmentStatement(Statement):
    """Mutation of one field on a nominal struct value."""

    object: Expression
    name: str
    name_token: Token
    value: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IfStatement(Statement):
    """Conditional branch statement with optional else branch."""

    condition: Expression
    then_branch: BlockStatement
    else_branch: BlockStatement | IfStatement | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class WhileStatement(Statement):
    """While loop statement."""

    condition: Expression
    body: BlockStatement
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ReturnStatement(Statement):
    """Return statement with optional return expression."""

    keyword: Token
    value: Expression | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class PrintStatement(Statement):
    """Built-in print statement."""

    keyword: Token
    expression: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ExpressionStatement(Statement):
    """Standalone expression evaluated as a statement."""

    expression: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LiteralExpression(Expression):
    """Literal constant expression (int, float, string, or bool)."""

    value: int | float | str | bool
    token: Token
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class VariableExpression(Expression):
    """Identifier reference expression."""

    name: str
    token: Token
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class UnaryExpression(Expression):
    """Prefix unary expression (`-` or `not`)."""

    operator: Token
    operand: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BinaryExpression(Expression):
    """Infix binary expression."""

    left: Expression
    operator: Token
    right: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class GroupingExpression(Expression):
    """Parenthesized expression `(expr)`."""

    expression: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class FunctionCallExpression(Expression):
    """Function invocation expression."""

    callee: str
    callee_token: Token
    arguments: tuple[Expression, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ArrayLiteralExpression(Expression):
    """Homogeneous typed array literal."""

    elements: tuple[Expression, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IndexExpression(Expression):
    """Array element lookup."""

    array: Expression
    index: Expression
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class MemberExpression(Expression):
    """Struct field lookup or enum variant qualification."""

    object: Expression
    name: str
    name_token: Token
    span: SourceSpan


def _node_label(node: ASTNode) -> str:
    if isinstance(node, Program):
        return "Program"
    if isinstance(node, ImportDeclaration):
        return f"Import {node.path}"
    if isinstance(node, StructDeclaration):
        return f"StructDeclaration {node.name}"
    if isinstance(node, StructField):
        return f"StructField {node.name}: {node.type_annotation.name}"
    if isinstance(node, EnumDeclaration):
        return f"EnumDeclaration {node.name}"
    if isinstance(node, FunctionDeclaration):
        params = ", ".join(f"{p.name}: {p.type_annotation.name}" for p in node.params)
        return f"FunctionDeclaration {node.name}({params}) -> {node.return_type.name}"
    if isinstance(node, Parameter):
        return f"Parameter {node.name}: {node.type_annotation.name}"
    if isinstance(node, VariableDeclaration):
        return f"VariableDeclaration {node.name}: {node.type_annotation.name if node.type_annotation else 'inferred'}"
    if isinstance(node, AssignmentStatement):
        return f"AssignmentStatement {node.name} ="
    if isinstance(node, IndexAssignmentStatement):
        return "IndexAssignmentStatement"
    if isinstance(node, MemberAssignmentStatement):
        return f"MemberAssignmentStatement .{node.name}"
    if isinstance(node, ArrayLiteralExpression):
        return f"ArrayLiteral[{len(node.elements)}]"
    if isinstance(node, IndexExpression):
        return "IndexExpression"
    if isinstance(node, MemberExpression):
        return f"MemberExpression .{node.name}"
    if isinstance(node, BlockStatement):
        return "BlockStatement"
    if isinstance(node, IfStatement):
        return "IfStatement"
    if isinstance(node, WhileStatement):
        return "WhileStatement"
    if isinstance(node, ReturnStatement):
        return "ReturnStatement"
    if isinstance(node, PrintStatement):
        return "PrintStatement"
    if isinstance(node, ExpressionStatement):
        return "ExpressionStatement"
    if isinstance(node, LiteralExpression):
        return f"Literal({node.value!r})"
    if isinstance(node, VariableExpression):
        return f"Variable({node.name})"
    if isinstance(node, UnaryExpression):
        return f"UnaryExpression({node.operator.lexeme})"
    if isinstance(node, BinaryExpression):
        return f"BinaryExpression({node.operator.lexeme})"
    if isinstance(node, GroupingExpression):
        return "GroupingExpression"
    if isinstance(node, FunctionCallExpression):
        return f"FunctionCall({node.callee})"
    return type(node).__name__


def _node_children(node: ASTNode) -> list[tuple[str | None, ASTNode]]:
    if isinstance(node, Program):
        return [(None, decl) for decl in node.declarations]
    if isinstance(node, StructDeclaration):
        return [(None, item) for item in node.fields]
    if isinstance(node, MemberAssignmentStatement):
        return [("object", node.object), ("value", node.value)]
    if isinstance(node, MemberExpression):
        return [("object", node.object)]
    if isinstance(node, FunctionDeclaration):
        return [("body", node.body)]
    if isinstance(node, VariableDeclaration):
        return [("initializer", node.initializer)]
    if isinstance(node, AssignmentStatement):
        return [("value", node.value)]
    if isinstance(node, IndexAssignmentStatement):
        return [("array", node.array), ("index", node.index), ("value", node.value)]
    if isinstance(node, ArrayLiteralExpression):
        return [(f"element[{i}]", item) for i, item in enumerate(node.elements)]
    if isinstance(node, IndexExpression):
        return [("array", node.array), ("index", node.index)]
    if isinstance(node, BlockStatement):
        return [(None, stmt) for stmt in node.statements]
    if isinstance(node, IfStatement):
        children: list[tuple[str | None, ASTNode]] = [
            ("condition", node.condition),
            ("then", node.then_branch),
        ]
        if node.else_branch is not None:
            children.append(("else", node.else_branch))
        return children
    if isinstance(node, WhileStatement):
        return [("condition", node.condition), ("body", node.body)]
    if isinstance(node, ReturnStatement):
        return [("value", node.value)] if node.value is not None else []
    if isinstance(node, PrintStatement):
        return [("expression", node.expression)]
    if isinstance(node, ExpressionStatement):
        return [(None, node.expression)]
    if isinstance(node, UnaryExpression):
        return [(None, node.operand)]
    if isinstance(node, BinaryExpression):
        return [(None, node.left), (None, node.right)]
    if isinstance(node, GroupingExpression):
        return [(None, node.expression)]
    if isinstance(node, FunctionCallExpression):
        return [(f"arg[{i}]", arg) for i, arg in enumerate(node.arguments)]
    return []


def format_ast(node: ASTNode) -> str:
    """Return a human-readable tree representation of an AST node."""
    lines: list[str] = [_node_label(node)]

    def _walk(current: ASTNode, prefix: str) -> None:
        children = _node_children(current)
        for index, (edge_label, child) in enumerate(children):
            is_last = index == len(children) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")
            label_text = f"{edge_label}: {_node_label(child)}" if edge_label else _node_label(child)
            lines.append(f"{prefix}{connector}{label_text}")
            _walk(child, child_prefix)

    _walk(node, "")
    return "\n".join(lines)
