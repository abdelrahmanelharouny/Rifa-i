"""Recursive Descent Parser for the Rifa'i programming language."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from rifai.errors.diagnostics import Diagnostic, DiagnosticPhase
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
    MemberExpression,
    MemberAssignmentStatement,
    ImportDeclaration,
    StructDeclaration,
    StructField,
    EnumDeclaration,
    IfStatement,
    LiteralExpression,
    Parameter,
    PrintStatement,
    Program,
    ReturnStatement,
    SourceSpan,
    Statement,
    TypeAnnotation,
    UnaryExpression,
    VariableDeclaration,
    VariableExpression,
    WhileStatement,
)
from rifai.frontend.tokens import Token, TokenType

_TYPE_TOKENS: Final[frozenset[TokenType]] = frozenset(
    {
        TokenType.TYPE_INT,
        TokenType.TYPE_FLOAT,
        TokenType.TYPE_BOOL,
        TokenType.TYPE_STRING,
        TokenType.TYPE_VOID,
    }
)

_SYNC_STARTERS: Final[frozenset[TokenType]] = frozenset(
    {
        TokenType.FN,
        TokenType.LET,
        TokenType.IF,
        TokenType.WHILE,
        TokenType.RETURN,
        TokenType.PRINT,
        TokenType.RIGHT_BRACE,
    }
)


class _ParseError(Exception):
    """Internal control-flow exception used for panic-mode recovery."""


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Output produced by the Rifa'i Parser."""

    program: Program
    diagnostics: tuple[Diagnostic, ...]

    @property
    def has_errors(self) -> bool:
        """Return True when one or more syntax errors were recorded."""
        return len(self.diagnostics) > 0


class Parser:
    """Recursive Descent Parser consuming a Rifa'i token stream."""

    def __init__(self, tokens: Sequence[Token]) -> None:
        if not tokens:
            self._tokens: tuple[Token, ...] = (
                Token(TokenType.EOF, "", None, 1, 1, 0, 0),
            )
        else:
            self._tokens = tuple(tokens)
        self._index = 0
        self._diagnostics: list[Diagnostic] = []

    def parse(self) -> ParseResult:
        """Parse the token stream into a Program AST and accumulated diagnostics."""
        self._index = 0
        self._diagnostics = []
        declarations: list[Statement] = []

        while not self._is_at_end():
            decl = self._parse_declaration()
            if decl is not None:
                declarations.append(decl)

        eof_token = self._peek()
        if declarations:
            program_span = SourceSpan.between(
                declarations[0].span, declarations[-1].span
            )
        else:
            program_span = SourceSpan.from_token(eof_token)

        return ParseResult(
            program=Program(declarations=tuple(declarations), span=program_span),
            diagnostics=tuple(self._diagnostics),
        )

    # --- Token navigation & error helpers ------------------------------------

    def _is_at_end(self) -> bool:
        return self._peek().token_type is TokenType.EOF

    def _peek(self, lookahead: int = 0) -> Token:
        pos = self._index + lookahead
        if pos >= len(self._tokens):
            return self._tokens[-1]
        return self._tokens[pos]

    def _previous(self) -> Token:
        return self._tokens[max(0, self._index - 1)]

    def _check(self, token_type: TokenType) -> bool:
        return self._peek().token_type is token_type

    def _advance(self) -> Token:
        token = self._peek()
        if token.token_type is not TokenType.EOF:
            self._index += 1
        return token

    def _match(self, *token_types: TokenType) -> Token | None:
        for token_type in token_types:
            if self._check(token_type):
                return self._advance()
        return None

    def _consume(self, token_type: TokenType, message: str) -> Token:
        if self._check(token_type):
            return self._advance()
        raise self._error(self._peek(), message)

    def _error(self, token: Token, message: str) -> _ParseError:
        self._diagnostics.append(
            Diagnostic(
                phase=DiagnosticPhase.PARSER,
                message=message,
                line=token.line,
                column=token.column,
                start_offset=token.start_offset,
                end_offset=token.end_offset,
            )
        )
        return _ParseError()

    def _synchronize(self) -> None:
        while not self._is_at_end():
            if self._previous().token_type is TokenType.SEMICOLON:
                return
            if self._peek().token_type in _SYNC_STARTERS:
                return
            self._advance()

    # --- Declarations & statements -------------------------------------------

    def _parse_declaration(self) -> Statement | None:
        saved_index = self._index
        try:
            if self._check(TokenType.IMPORT):
                return self._parse_import_declaration()
            if self._check(TokenType.STRUCT):
                return self._parse_struct_declaration()
            if self._check(TokenType.ENUM):
                return self._parse_enum_declaration()
            if self._check(TokenType.FN):
                return self._parse_function_declaration()
            return self._parse_statement()
        except _ParseError:
            self._synchronize()
            # Prevent infinite loop: if recovery didn't advance, force it.
            if self._index == saved_index:
                self._advance()
            return None

    def _parse_import_declaration(self) -> ImportDeclaration:
        keyword = self._consume(TokenType.IMPORT, "Expected 'import'.")
        path = self._consume(TokenType.STRING, "Expected a quoted relative module path.")
        semi = self._consume(TokenType.SEMICOLON, "Expected ';' after import.")
        return ImportDeclaration(
            path=str(path.literal),
            path_token=path,
            span=SourceSpan.between(keyword, semi),
        )

    def _parse_struct_declaration(self) -> StructDeclaration:
        keyword = self._consume(TokenType.STRUCT, "Expected 'struct'.")
        name = self._consume(TokenType.IDENTIFIER, "Expected struct name.")
        self._consume(TokenType.LEFT_BRACE, "Expected '{' after struct name.")
        fields: list[StructField] = []
        while not self._check(TokenType.RIGHT_BRACE) and not self._is_at_end():
            field_name = self._consume(TokenType.IDENTIFIER, "Expected struct field name.")
            self._consume(TokenType.COLON, "Expected ':' after struct field name.")
            field_type = self._parse_type_annotation("Expected struct field type.")
            end: Token | SourceSpan = field_type.span
            if self._match(TokenType.COMMA, TokenType.SEMICOLON) is not None:
                end = self._previous()
            elif not self._check(TokenType.RIGHT_BRACE):
                raise self._error(self._peek(), "Expected ',' or ';' after struct field.")
            fields.append(StructField(
                name=field_name.lexeme,
                name_token=field_name,
                type_annotation=field_type,
                span=SourceSpan.between(field_name, end),
            ))
        close = self._consume(TokenType.RIGHT_BRACE, "Expected '}' after struct fields.")
        return StructDeclaration(
            name=name.lexeme,
            name_token=name,
            fields=tuple(fields),
            span=SourceSpan.between(keyword, close),
        )

    def _parse_enum_declaration(self) -> EnumDeclaration:
        keyword = self._consume(TokenType.ENUM, "Expected 'enum'.")
        name = self._consume(TokenType.IDENTIFIER, "Expected enum name.")
        self._consume(TokenType.LEFT_BRACE, "Expected '{' after enum name.")
        variants: list[Token] = []
        if not self._check(TokenType.RIGHT_BRACE):
            while True:
                variants.append(self._consume(TokenType.IDENTIFIER, "Expected enum variant name."))
                if self._match(TokenType.COMMA) is None:
                    break
                if self._check(TokenType.RIGHT_BRACE):
                    break
        close = self._consume(TokenType.RIGHT_BRACE, "Expected '}' after enum variants.")
        return EnumDeclaration(
            name=name.lexeme,
            name_token=name,
            variants=tuple(variants),
            span=SourceSpan.between(keyword, close),
        )

    def _parse_function_declaration(self) -> FunctionDeclaration:
        fn_token = self._consume(TokenType.FN, "Expected 'fn' keyword.")
        name_token = self._consume(TokenType.IDENTIFIER, "Expected function name.")
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after function name.")

        params: list[Parameter] = []
        if not self._check(TokenType.RIGHT_PAREN):
            while True:
                param_name = self._consume(
                    TokenType.IDENTIFIER, "Expected parameter name."
                )
                self._consume(TokenType.COLON, "Expected ':' after parameter name.")
                param_type = self._parse_type_annotation("Expected parameter type.")
                params.append(
                    Parameter(
                        name=param_name.lexeme,
                        name_token=param_name,
                        type_annotation=param_type,
                        span=SourceSpan.between(param_name, param_type.span),
                    )
                )
                if self._match(TokenType.COMMA) is None:
                    break

        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after parameters.")
        self._consume(TokenType.ARROW, "Expected '->' before function return type.")
        return_type = self._parse_type_annotation("Expected function return type.")
        if not self._check(TokenType.LEFT_BRACE):
            raise self._error(self._peek(), "Expected '{' before function body.")
        body = self._parse_block()

        return FunctionDeclaration(
            name=name_token.lexeme,
            name_token=name_token,
            params=tuple(params),
            return_type=return_type,
            body=body,
            span=SourceSpan.between(fn_token, body.span),
        )

    def _parse_type_annotation(self, message: str) -> TypeAnnotation:
        token = self._peek()
        if token.token_type in _TYPE_TOKENS or token.token_type is TokenType.IDENTIFIER:
            self._advance()
            end: Token | SourceSpan = token
            name = token.lexeme
            if self._match(TokenType.LEFT_BRACKET) is not None:
                close = self._consume(
                    TokenType.RIGHT_BRACKET,
                    "Expected ']' after array type brackets.",
                )
                name += "[]"
                end = close
            return TypeAnnotation(
                name=name,
                token=token,
                span=SourceSpan.between(token, end),
            )
        raise self._error(token, message)

    def _parse_statement(self) -> Statement:
        if self._check(TokenType.FN):
            raise self._error(
                self._peek(), "Nested function declarations are not allowed."
            )
        if self._check(TokenType.LET):
            return self._parse_variable_declaration()
        if self._check(TokenType.IF):
            return self._parse_if_statement()
        if self._check(TokenType.WHILE):
            return self._parse_while_statement()
        if self._check(TokenType.RETURN):
            return self._parse_return_statement()
        if self._check(TokenType.PRINT):
            return self._parse_print_statement()
        if self._check(TokenType.LEFT_BRACE):
            return self._parse_block()
        if (
            self._check(TokenType.IDENTIFIER)
            and self._peek(1).token_type is TokenType.ASSIGN
        ):
            return self._parse_assignment_statement()
        if (
            self._check(TokenType.IDENTIFIER)
            and self._peek(1).token_type is TokenType.LEFT_BRACKET
        ):
            return self._parse_index_or_expression_statement()
        return self._parse_expression_statement()

    def _parse_variable_declaration(self) -> VariableDeclaration:
        let_token = self._consume(TokenType.LET, "Expected 'let'.")
        name_token = self._consume(TokenType.IDENTIFIER, "Expected variable name.")
        type_ann = None
        if self._match(TokenType.COLON) is not None:
            type_ann = self._parse_type_annotation("Expected variable type annotation.")
        self._consume(TokenType.ASSIGN, "Expected '=' after variable name or type.")
        initializer = self._parse_expression()
        semi = self._consume(
            TokenType.SEMICOLON, "Expected ';' after variable declaration."
        )
        return VariableDeclaration(
            name=name_token.lexeme,
            name_token=name_token,
            type_annotation=type_ann,
            initializer=initializer,
            span=SourceSpan.between(let_token, semi),
        )

    def _parse_assignment_statement(self) -> AssignmentStatement:
        name_token = self._consume(TokenType.IDENTIFIER, "Expected variable name.")
        self._consume(TokenType.ASSIGN, "Expected '=' in assignment.")
        value = self._parse_expression()
        semi = self._consume(TokenType.SEMICOLON, "Expected ';' after assignment.")
        return AssignmentStatement(
            name=name_token.lexeme,
            name_token=name_token,
            value=value,
            span=SourceSpan.between(name_token, semi),
        )

    def _parse_index_or_expression_statement(self) -> Statement:
        expression = self._parse_expression()
        if self._match(TokenType.ASSIGN) is not None:
            value = self._parse_expression()
            semi = self._consume(TokenType.SEMICOLON, "Expected ';' after assignment.")
            if isinstance(expression, IndexExpression):
                return IndexAssignmentStatement(
                    array=expression.array,
                    index=expression.index,
                    value=value,
                    span=SourceSpan.between(expression.span, semi),
                )
            if isinstance(expression, MemberExpression):
                return MemberAssignmentStatement(
                    object=expression.object,
                    name=expression.name,
                    name_token=expression.name_token,
                    value=value,
                    span=SourceSpan.between(expression.span, semi),
                )
            raise self._error(self._previous(), "Only array elements and struct fields can be assigned through postfix access.")
        semi = self._consume(TokenType.SEMICOLON, "Expected ';' after expression.")
        return ExpressionStatement(
            expression=expression,
            span=SourceSpan.between(expression.span, semi),
        )

    def _parse_block(self) -> BlockStatement:
        open_brace = self._consume(TokenType.LEFT_BRACE, "Expected '{'.")
        statements: list[Statement] = []

        while not self._check(TokenType.RIGHT_BRACE) and not self._is_at_end():
            saved_index = self._index
            try:
                statements.append(self._parse_statement())
            except _ParseError:
                self._synchronize()
                # Prevent infinite loop: if recovery didn't advance, force it.
                if self._index == saved_index:
                    self._advance()

        close_brace = self._consume(
            TokenType.RIGHT_BRACE, "Expected '}' after block."
        )
        return BlockStatement(
            statements=tuple(statements),
            span=SourceSpan.between(open_brace, close_brace),
        )

    def _parse_if_statement(self) -> IfStatement:
        if_token = self._consume(TokenType.IF, "Expected 'if'.")
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'if'.")
        condition = self._parse_expression()
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after if condition.")

        if not self._check(TokenType.LEFT_BRACE):
            raise self._error(self._peek(), "Expected '{' before if body.")
        then_branch = self._parse_block()

        else_branch: BlockStatement | IfStatement | None = None
        if self._match(TokenType.ELSE) is not None:
            if self._check(TokenType.IF):
                else_branch = self._parse_if_statement()
            elif self._check(TokenType.LEFT_BRACE):
                else_branch = self._parse_block()
            else:
                raise self._error(self._peek(), "Expected '{' or 'if' after 'else'.")

        end_span = else_branch.span if else_branch is not None else then_branch.span
        return IfStatement(
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch,
            span=SourceSpan.between(if_token, end_span),
        )

    def _parse_while_statement(self) -> WhileStatement:
        while_token = self._consume(TokenType.WHILE, "Expected 'while'.")
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'while'.")
        condition = self._parse_expression()
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after while condition.")
        if not self._check(TokenType.LEFT_BRACE):
            raise self._error(self._peek(), "Expected '{' before while body.")
        body = self._parse_block()
        return WhileStatement(
            condition=condition,
            body=body,
            span=SourceSpan.between(while_token, body.span),
        )

    def _parse_return_statement(self) -> ReturnStatement:
        keyword = self._consume(TokenType.RETURN, "Expected 'return'.")
        value: Expression | None = None
        if not self._check(TokenType.SEMICOLON):
            value = self._parse_expression()
        semi = self._consume(
            TokenType.SEMICOLON, "Expected ';' after return statement."
        )
        return ReturnStatement(
            keyword=keyword,
            value=value,
            span=SourceSpan.between(keyword, semi),
        )

    def _parse_print_statement(self) -> PrintStatement:
        keyword = self._consume(TokenType.PRINT, "Expected 'print'.")
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'print'.")
        expression = self._parse_expression()
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after print argument.")
        semi = self._consume(
            TokenType.SEMICOLON, "Expected ';' after print statement."
        )
        return PrintStatement(
            keyword=keyword,
            expression=expression,
            span=SourceSpan.between(keyword, semi),
        )

    def _parse_expression_statement(self) -> ExpressionStatement:
        expr = self._parse_expression()
        semi = self._consume(TokenType.SEMICOLON, "Expected ';' after expression.")
        return ExpressionStatement(
            expression=expr,
            span=SourceSpan.between(expr.span, semi),
        )

    # --- Expressions (precedence climbing via layered recursive descent) -----

    def _parse_expression(self) -> Expression:
        return self._parse_or()

    def _parse_or(self) -> Expression:
        expr = self._parse_and()
        while (op := self._match(TokenType.OR)) is not None:
            right = self._parse_and()
            expr = BinaryExpression(
                left=expr,
                operator=op,
                right=right,
                span=SourceSpan.between(expr.span, right.span),
            )
        return expr

    def _parse_and(self) -> Expression:
        expr = self._parse_equality()
        while (op := self._match(TokenType.AND)) is not None:
            right = self._parse_equality()
            expr = BinaryExpression(
                left=expr,
                operator=op,
                right=right,
                span=SourceSpan.between(expr.span, right.span),
            )
        return expr

    def _parse_equality(self) -> Expression:
        expr = self._parse_comparison()
        while (op := self._match(TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL)) is not None:
            right = self._parse_comparison()
            expr = BinaryExpression(
                left=expr,
                operator=op,
                right=right,
                span=SourceSpan.between(expr.span, right.span),
            )
        return expr

    def _parse_comparison(self) -> Expression:
        expr = self._parse_term()
        while (
            op := self._match(
                TokenType.LESS,
                TokenType.LESS_EQUAL,
                TokenType.GREATER,
                TokenType.GREATER_EQUAL,
            )
        ) is not None:
            right = self._parse_term()
            expr = BinaryExpression(
                left=expr,
                operator=op,
                right=right,
                span=SourceSpan.between(expr.span, right.span),
            )
        return expr

    def _parse_term(self) -> Expression:
        expr = self._parse_factor()
        while (op := self._match(TokenType.PLUS, TokenType.MINUS)) is not None:
            right = self._parse_factor()
            expr = BinaryExpression(
                left=expr,
                operator=op,
                right=right,
                span=SourceSpan.between(expr.span, right.span),
            )
        return expr

    def _parse_factor(self) -> Expression:
        expr = self._parse_unary()
        while (
            op := self._match(TokenType.STAR, TokenType.SLASH, TokenType.MODULO)
        ) is not None:
            right = self._parse_unary()
            expr = BinaryExpression(
                left=expr,
                operator=op,
                right=right,
                span=SourceSpan.between(expr.span, right.span),
            )
        return expr

    def _parse_unary(self) -> Expression:
        if (op := self._match(TokenType.MINUS, TokenType.NOT)) is not None:
            operand = self._parse_unary()
            return UnaryExpression(
                operator=op,
                operand=operand,
                span=SourceSpan.between(op, operand.span),
            )
        return self._parse_primary()

    def _parse_primary(self) -> Expression:
        expression: Expression
        if (
            token := self._match(
                TokenType.INTEGER,
                TokenType.FLOAT,
                TokenType.STRING,
                TokenType.TRUE,
                TokenType.FALSE,
            )
        ) is not None:
            assert token.literal is not None
            expression = LiteralExpression(
                value=token.literal,
                token=token,
                span=SourceSpan.from_token(token),
            )
        elif (ident := self._match(TokenType.IDENTIFIER)) is not None:
            if self._match(TokenType.LEFT_PAREN) is not None:
                expression = self._finish_function_call(ident)
            else:
                expression = VariableExpression(
                    name=ident.lexeme,
                    token=ident,
                    span=SourceSpan.from_token(ident),
                )
        elif (open_paren := self._match(TokenType.LEFT_PAREN)) is not None:
            inner = self._parse_expression()
            close_paren = self._consume(
                TokenType.RIGHT_PAREN, "Expected ')' after expression."
            )
            expression = GroupingExpression(
                expression=inner,
                span=SourceSpan.between(open_paren, close_paren),
            )
        elif (open_bracket := self._match(TokenType.LEFT_BRACKET)) is not None:
            elements: list[Expression] = []
            if not self._check(TokenType.RIGHT_BRACKET):
                while True:
                    elements.append(self._parse_expression())
                    if self._match(TokenType.COMMA) is None:
                        break
            close_bracket = self._consume(
                TokenType.RIGHT_BRACKET, "Expected ']' after array literal."
            )
            expression = ArrayLiteralExpression(
                elements=tuple(elements),
                span=SourceSpan.between(open_bracket, close_bracket),
            )
        else:
            current = self._peek()
            if current.token_type is TokenType.EOF:
                raise self._error(current, "Unexpected end of file; expected expression.")
            raise self._error(current, f"Expected expression, got '{current.lexeme}'.")

        while True:
            if self._match(TokenType.LEFT_BRACKET) is not None:
                index = self._parse_expression()
                close_bracket = self._consume(
                    TokenType.RIGHT_BRACKET, "Expected ']' after array index."
                )
                expression = IndexExpression(
                    array=expression,
                    index=index,
                    span=SourceSpan.between(expression.span, close_bracket),
                )
                continue
            if self._match(TokenType.DOT) is not None:
                member = self._consume(TokenType.IDENTIFIER, "Expected member name after '.'.")
                expression = MemberExpression(
                    object=expression,
                    name=member.lexeme,
                    name_token=member,
                    span=SourceSpan.between(expression.span, member),
                )
                continue
            break
        return expression

    def _finish_function_call(self, callee: Token) -> FunctionCallExpression:
        arguments: list[Expression] = []
        if not self._check(TokenType.RIGHT_PAREN):
            while True:
                arguments.append(self._parse_expression())
                if self._match(TokenType.COMMA) is None:
                    break

        close_paren = self._consume(
            TokenType.RIGHT_PAREN, "Expected ')' after function arguments."
        )
        return FunctionCallExpression(
            callee=callee.lexeme,
            callee_token=callee,
            arguments=tuple(arguments),
            span=SourceSpan.between(callee, close_paren),
        )
