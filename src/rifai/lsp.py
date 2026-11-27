"""Language Server Protocol server for Rifa'i (JSON-RPC 2.0 over stdio)."""
from __future__ import annotations

import argparse
import bisect
import json
import sys
from dataclasses import dataclass, fields
from typing import Any, BinaryIO

from rifai import __version__
from rifai.frontend.ast_nodes import ASTNode, AssignmentStatement, FunctionCallExpression, FunctionDeclaration, Parameter, VariableDeclaration, VariableExpression
from rifai.frontend.lexer import LexResult, Lexer
from rifai.frontend.parser import Parser
from rifai.frontend.semantic import SemanticAnalyzer
from rifai.frontend.symbol_table import FunctionSymbol, VariableSymbol
from rifai.frontend.tokens import Token, TokenType

MAX_MESSAGE_BYTES = 16 *  1024 * 1024
MAX_HEADER_BYTES = 8192
KEYWORDS = ("fn", "let", "return", "if", "else", "while", "print", "true", "false", "and", "or", "not", "len", "push", "pop")
TYPES = ("int", "float", "bool", "string", "int[]", "float[]", "bool[]", "string[]", "void")


class ProtocolError(Exception):
    pass


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Analysis:
    source: str
    lex: LexResult
    program: ASTNode | None
    semantic: Any
    diagnostics: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Document:
    uri: str
    source: str
    version: int
    analysis: Analysis


@dataclass(frozen=True, slots=True)
class Occurrence:
    token: Token
    symbol: VariableSymbol | FunctionSymbol
    declaration: bool


def _analyze(source: str) -> Analysis:
    lex = Lexer(source).scan_tokens()
    if lex.has_errors:
        return Analysis(source, lex, None, None, lex.diagnostics)
    parsed = Parser(lex.tokens).parse()
    if parsed.has_errors:
        return Analysis(source, lex, parsed.program, None, parsed.diagnostics)
    semantic = SemanticAnalyzer().analyze(parsed.program)
    return Analysis(source, lex, parsed.program, semantic, semantic.diagnostics)


def _walk(node: ASTNode):
    yield node
    for descriptor in fields(node):
        value = getattr(node, descriptor.name)
        if isinstance(value, ASTNode):
            yield from _walk(value)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, ASTNode):
                    yield from _walk(item)


def _signature(symbol: FunctionSymbol) -> str:
    args = ", ".join(f"{p.name}: {p.rifai_type.value}" for p in symbol.params)
    return f"{symbol.name}({args}) -> {symbol.return_type.value}"


def _line_starts(source: str) -> list[int]:
    return [0, *(i + 1 for i, ch in enumerate(source) if ch == "\n")]


def _utf16(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _offset_at(source: str, position: dict[str, Any]) -> int:
    starts = _line_starts(source)
    line = max(0, min(int(position.get("line", 0)), len(starts) - 1))
    start = starts[line]
    end = source.find("\n", start)
    if end < 0:
        end = len(source)
    elif end > start and source[end - 1] == "\r":
        end -= 1
    remaining = max(0, int(position.get("character", 0)))
    index = start
    while index < end and remaining:
        width = _utf16(source[index])
        if width > remaining:
            break
        remaining -= width
        index += 1
    return index


def _position_at(source: str, offset: int) -> dict[str, int]:
    offset = max(0, min(offset, len(source)))
    starts = _line_starts(source)
    line = max(0, bisect.bisect_right(starts, offset) - 1)
    start = starts[line]
    end = source.find("\n", start)
    if end < 0:
        end = len(source)
    elif end > start and source[end - 1] == "\r":
        end -= 1
    return {"line": line, "character": _utf16(source[start:min(offset, end)])}


def _range(source: str, start: int, end: int) -> dict[str, Any]:
    start = max(0, min(start, len(source)))
    end = max(start, min(end, len(source)))
    return {"start": _position_at(source, start), "end": _position_at(source, end)}


def _token_range(source: str, token: Token) -> dict[str, Any]:
    return _range(source, token.start_offset, token.end_offset)


def _diagnostic_range(source: str, item: Any) -> dict[str, Any]:
    if item.start_offset is not None:
        return _range(source, item.start_offset, item.end_offset or item.start_offset)
    starts = _line_starts(source)
    line = max(0, min(item.line - 1, len(starts) - 1))
    start = min(starts[line] + max(0, item.column - 1), len(source))
    return _range(source, start, min(start + 1, len(source)))


def _lsp_diagnostic(source: str, item: Any) -> dict[str, Any]:
    return {"range": _diagnostic_range(source, item), "severity": 1,
            "code": item.phase.value, "source": "rifai", "message": item.message}


def _occurrences(analysis: Analysis) -> list[Occurrence]:
    if analysis.program is None or analysis.semantic is None:
        return []
    result: list[Occurrence] = []
    semantic = analysis.semantic
    for node in _walk(analysis.program):
        token = None
        symbol = None
        declaration = False
        if isinstance(node, VariableDeclaration):
            token, symbol, declaration = node.name_token, semantic.variable_for(node), True
        elif isinstance(node, AssignmentStatement):
            token, symbol = node.name_token, semantic.variable_for(node)
        elif isinstance(node, VariableExpression):
            token, symbol = node.token, semantic.variable_for(node)
        elif isinstance(node, Parameter):
            token, symbol, declaration = node.name_token, semantic.variable_bindings.get(id(node)), True
        elif isinstance(node, FunctionDeclaration):
            token, symbol, declaration = node.name_token, semantic.function_for(node), True
        elif isinstance(node, FunctionCallExpression):
            token, symbol = node.callee_token, semantic.function_for(node)
        if token is not None and symbol is not None:
            result.append(Occurrence(token, symbol, declaration))
    return result


def _symbol_detail(symbol: VariableSymbol | FunctionSymbol) -> str:
    if isinstance(symbol, FunctionSymbol):
        return _signature(symbol)
    scope = "global" if symbol.is_global else ("parameter" if symbol.is_parameter else "local")
    return f"{scope} {symbol.rifai_type.value}"


class LanguageServer:
    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.notifications: list[dict[str, Any]] = []
        self.shutdown_requested = False
        self.running = True

    def take_notifications(self) -> list[dict[str, Any]]:
        result, self.notifications = self.notifications, []
        return result

    def _publish(self, uri: str, source: str, analysis: Analysis) -> None:
        diagnostics = [_lsp_diagnostic(source, item) for item in analysis.diagnostics]
        self.notifications.append({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                                   "params": {"uri": uri, "diagnostics": diagnostics}})

    def _store(self, uri: str, source: str, version: int) -> None:
        analysis = _analyze(source)
        self.documents[uri] = Document(uri, source, version, analysis)
        self._publish(uri, source, analysis)

    def handle_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "exit":
            self.running = False
            return
        if method == "$/cancelRequest":
            return
        if method == "textDocument/didOpen":
            doc = params.get("textDocument") or {}
            uri, source, version = doc.get("uri"), doc.get("text"), doc.get("version", 0)
            if isinstance(uri, str) and isinstance(source, str):
                self._store(uri, source, version if type(version) is int else 0)
            return
        if method == "textDocument/didChange":
            doc = params.get("textDocument") or {}
            uri, changes = doc.get("uri"), params.get("contentChanges") or []
            old = self.documents.get(uri) if isinstance(uri, str) else None
            if old is None or not changes:
                return
            version = doc.get("version", old.version + 1)
            if type(version) is not int or version < old.version:
                return
            source = changes[-1].get("text")
            if isinstance(source, str):
                self._store(uri, source, version)
            return
        if method == "textDocument/didSave":
            doc = params.get("textDocument") or {}
            uri, source = doc.get("uri"), params.get("text")
            if isinstance(uri, str) and uri in self.documents and isinstance(source, str):
                self._store(uri, source, self.documents[uri].version)
            return
        if method == "textDocument/didClose":
            doc = params.get("textDocument") or {}
            uri = doc.get("uri")
            if isinstance(uri, str):
                self.documents.pop(uri, None)
                self.notifications.append({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                                           "params": {"uri": uri, "diagnostics": []}})

    def _document(self, params: dict[str, Any]) -> Document:
        doc = params.get("textDocument") or {}
        uri = doc.get("uri")
        if not isinstance(uri, str) or uri not in self.documents:
            raise RpcError(-32002, "The requested document is not open.")
        return self.documents[uri]

    @staticmethod
    def _position(params: dict[str, Any]) -> dict[str, Any]:
        value = params.get("position")
        if not isinstance(value, dict):
            raise RpcError(-32602, "A valid document position is required.")
        return value

    def handle_request(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            return {"capabilities": {
                "textDocumentSync": {"openClose": True, "change": 1, "save": {"includeText": False}},
                "completionProvider": {"resolveProvider": False, "triggerCharacters": list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")},
                "hoverProvider": True, "definitionProvider": True, "referencesProvider": True,
                "documentSymbolProvider": True,
                "signatureHelpProvider": {"triggerCharacters": ["(", ","], "retriggerCharacters": [","]},
            }, "serverInfo": {"name": "Rifa'i Language Server", "version": __version__}}
        if method == "shutdown":
            self.shutdown_requested = True
            return None
        if method == "textDocument/completion":
            return self._completion(self._document(params), params)
        if method == "textDocument/hover":
            return self._hover(self._document(params), params)
        if method == "textDocument/definition":
            return self._definition(self._document(params), params)
        if method == "textDocument/references":
            return self._references(self._document(params), params)
        if method == "textDocument/documentSymbol":
            return self._document_symbols(self._document(params))
        if method == "textDocument/signatureHelp":
            return self._signature_help(self._document(params), params)
        raise RpcError(-32601, f"Method not found: {method}")

    def _completion(self, doc: Document, params: dict[str, Any]) -> dict[str, Any]:
        offset = _offset_at(doc.source, self._position(params))
        start = offset
        while start and (doc.source[start - 1] == "_" or doc.source[start - 1].isascii() and doc.source[start - 1].isalnum()):
            start -= 1
        prefix = doc.source[start:offset]
        items: list[dict[str, Any]] = []
        for word in KEYWORDS:
            items.append({"label": word, "kind": 14, "detail": "Rifa'i keyword", "insertText": word, "sortText": "2" + word})
        for word in TYPES:
            items.append({"label": word, "kind": 7, "detail": "Built-in type", "insertText": word, "sortText": "1" + word})
        analysis = doc.analysis
        symbols: dict[str, VariableSymbol | FunctionSymbol] = {}
        if analysis.semantic is not None:
            symbols.update(analysis.semantic.global_symbols)
            if analysis.program is not None:
                for node in _walk(analysis.program):
                    if isinstance(node, VariableDeclaration) and node.span.start_offset <= offset:
                        symbol = analysis.semantic.variable_for(node)
                        if symbol is not None:
                            symbols[symbol.name] = symbol
                    elif isinstance(node, Parameter):
                        symbol = analysis.semantic.variable_bindings.get(id(node))
                        if symbol is not None:
                            symbols.setdefault(symbol.name, symbol)
        for name, symbol in sorted(symbols.items()):
            if isinstance(symbol, FunctionSymbol):
                items.append({"label": _signature(symbol), "filterText": name, "kind": 3,
                              "detail": "function", "insertText": name, "sortText": "0" + name})
            else:
                items.append({"label": name, "kind": 6, "detail": _symbol_detail(symbol),
                              "insertText": name, "sortText": "0" + name})
        if prefix:
            items = [item for item in items if item.get("filterText", item["label"]).startswith(prefix)]
        return {"isIncomplete": False, "items": items}

    def _occurrence_at(self, doc: Document, params: dict[str, Any]) -> Occurrence | None:
        offset = _offset_at(doc.source, self._position(params))
        found = [item for item in _occurrences(doc.analysis)
                 if item.token.start_offset <= offset <= item.token.end_offset]
        return min(found, key=lambda item: item.token.end_offset-item.token.start_offset) if found else None

    def _hover(self, doc: Document, params: dict[str, Any]) -> dict[str, Any] | None:
        occurrence = self._occurrence_at(doc, params)
        if occurrence is None:
            return None
        symbol = occurrence.symbol
        if isinstance(symbol, FunctionSymbol):
            value = f"**{_signature(symbol)}**\n\nFunction"
        else:
            value = f"**{symbol.name}: {symbol.rifai_type.value}**\n\n{_symbol_detail(symbol)}"
        return {"contents": {"kind": "markdown", "value": value},
                "range": _token_range(doc.source, occurrence.token)}

    def _definition(self, doc: Document, params: dict[str, Any]) -> list[dict[str, Any]]:
        occurrence = self._occurrence_at(doc, params)
        if occurrence is None:
            return []
        declaration = next(
            (item for item in _occurrences(doc.analysis)
             if item.symbol is occurrence.symbol and item.declaration),
            None,
        )
        if declaration is None:
            return []
        return [{"uri": doc.uri, "range": _token_range(doc.source, declaration.token)}]

    def _references(self, doc: Document, params: dict[str, Any]) -> list[dict[str, Any]]:
        occurrence = self._occurrence_at(doc, params)
        if occurrence is None:
            return []
        include_decl = bool((params.get("context") or {}).get("includeDeclaration", False))
        return [{"uri": doc.uri, "range": _token_range(doc.source, item.token)}
                for item in _occurrences(doc.analysis)
                if item.symbol is occurrence.symbol and (include_decl or not item.declaration)]

    def _document_symbols(self, doc: Document) -> list[dict[str, Any]]:
        analysis = doc.analysis
        if analysis.program is None or analysis.semantic is None:
            return []
        semantic = analysis.semantic
        output = []
        for node in analysis.program.declarations:
            if isinstance(node, FunctionDeclaration):
                symbol = semantic.function_for(node)
                if symbol is None:
                    continue
                children = []
                for param in node.params:
                    item = semantic.variable_bindings.get(id(param))
                    if item is not None:
                        children.append({"name": item.name, "kind": 13, "detail": item.rifai_type.value,
                                         "range": _range(doc.source, param.span.start_offset, param.span.end_offset),
                                         "selectionRange": _token_range(doc.source, param.name_token)})
                for child in _walk(node.body):
                    if isinstance(child, VariableDeclaration):
                        item = semantic.variable_for(child)
                        if item is not None:
                            children.append({"name": item.name, "kind": 13, "detail": item.rifai_type.value,
                                             "range": _range(doc.source, child.span.start_offset, child.span.end_offset),
                                             "selectionRange": _token_range(doc.source, child.name_token)})
                output.append({"name": symbol.name, "kind": 12, "detail": _signature(symbol),
                               "range": _range(doc.source, node.span.start_offset, node.span.end_offset),
                               "selectionRange": _token_range(doc.source, node.name_token), "children": children})
            elif isinstance(node, VariableDeclaration):
                item = semantic.variable_for(node)
                if item is not None:
                    output.append({"name": item.name, "kind": 13, "detail": item.rifai_type.value,
                                   "range": _range(doc.source, node.span.start_offset, node.span.end_offset),
                                   "selectionRange": _token_range(doc.source, node.name_token)})
        return output

    def _signature_help(self, doc: Document, params: dict[str, Any]) -> dict[str, Any] | None:
        analysis = doc.analysis
        if analysis.program is None or analysis.semantic is None:
            return None
        offset = _offset_at(doc.source, self._position(params))
        calls = [node for node in _walk(analysis.program)
                 if isinstance(node, FunctionCallExpression) and node.span.start_offset <= offset <= node.span.end_offset]
        if not calls:
            return None
        call = min(calls, key=lambda item: item.span.end_offset-item.span.start_offset)
        symbol = analysis.semantic.function_for(call)
        if symbol is None:
            return None
        active = 0
        depth = 0
        for token in analysis.lex.tokens:
            if token.start_offset < call.callee_token.end_offset or token.start_offset >= offset:
                continue
            if token.token_type is TokenType.LEFT_PAREN:
                depth += 1
            elif token.token_type is TokenType.RIGHT_PAREN:
                depth = max(0, depth - 1)
            elif token.token_type is TokenType.COMMA and depth == 1:
                active += 1
        parameters = [{"label": f"{p.name}: {p.rifai_type.value}"} for p in symbol.params]
        active = min(active, max(0, len(parameters) - 1))
        return {"signatures": [{"label": _signature(symbol), "parameters": parameters,
                                "activeParameter": active}],
                "activeSignature": 0, "activeParameter": active}


def read_message(stream: BinaryIO) -> bytes | None:
    headers: dict[str, str] = {}
    consumed = 0
    while True:
        line = stream.readline(MAX_HEADER_BYTES + 1)
        if not line:
            if consumed == 0:
                return None
            raise ProtocolError("Unexpected EOF in LSP headers.")
        consumed += len(line)
        if consumed > MAX_HEADER_BYTES:
            raise ProtocolError("LSP headers exceed size limit.")
        if line in (b"\r\n", b"\n"):
            break
        try:
            key, value = line.decode("ascii").split(":", 1)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProtocolError("Malformed LSP header.") from exc
        key = key.strip().lower()
        if key in headers:
            raise ProtocolError(f"Duplicate LSP header: {key}")
        headers[key] = value.strip()
    raw_length = headers.get("content-length")
    if raw_length is None or not raw_length.isdigit():
        raise ProtocolError("A valid Content-Length header is required.")
    length = int(raw_length)
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError("LSP message exceeds size limit.")
    body = stream.read(length)
    if len(body) != length:
        raise ProtocolError("Truncated LSP message body.")
    return body


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def serve(input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None) -> int:
    source = input_stream or sys.stdin.buffer
    target = output_stream or sys.stdout.buffer
    server = LanguageServer()
    while server.running:
        try:
            body = read_message(source)
        except ProtocolError as exc:
            print(f"Rifa'i LSP protocol error: {exc}", file=sys.stderr)
            return 1
        if body is None:
            break
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            write_message(target, {"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32700, "message": f"Parse error: {exc}"}})
            continue
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            write_message(target, {"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        method, params = message.get("method"), message.get("params") or {}
        request_id = message.get("id")
        if not isinstance(method, str) or not isinstance(params, dict):
            if "id" in message:
                write_message(target, {"jsonrpc": "2.0", "id": request_id,
                                       "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        if "id" not in message:
            try:
                server.handle_notification(method, params)
            except Exception as exc:
                print(f"Rifa'i LSP notification error ({method}): {exc}", file=sys.stderr)
        else:
            try:
                result = server.handle_request(method, params)
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
            except RpcError as exc:
                response = {"jsonrpc": "2.0", "id": request_id,
                            "error": {"code": exc.code, "message": str(exc)}}
            except Exception as exc:
                print(f"Rifa'i LSP request error ({method}): {exc}", file=sys.stderr)
                response = {"jsonrpc": "2.0", "id": request_id,
                            "error": {"code": -32603, "message": "Internal error"}}
            write_message(target, response)
        for notification in server.take_notifications():
            write_message(target, notification)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rifai-lsp", description="Run the Rifa'i language server over stdio.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
