# Phase 6 — Developer Experience

## Scope and delivery

Phase 6 adds editor tooling without changing the Rifa'i language grammar, bytecode format, or virtual machine. All editor intelligence reuses the compiler's existing lexer, parser, semantic analyzer, source spans, and symbol bindings.

### 1. Language Server

The server is available as both:

- **rifai-lsp**
- **rifai lsp**

It uses JSON-RPC 2.0 over stdio with Content-Length framing and only Python's standard library. The implementation includes bounded message/header sizes, UTF-8 payloads, stderr-only diagnostics for server failures, and clean notification/request handling.

Implemented LSP capabilities:

| Capability | Behavior |
|---|---|
| Initialize / shutdown / exit | Server lifecycle and capability negotiation |
| Document open / change / save / close | Open-document state and diagnostics refresh |
| Diagnostics | Lexer, parser, and semantic errors mapped to LSP ranges |
| Completion | Language keywords, built-in types, globals, functions, parameters, and prior local declarations |
| Hover | Function signatures and resolved variable types |
| Go to Definition | Declaration token range for resolved variables and functions |
| Find References | References in the currently open document, optionally including declarations |
| Document Symbols | Top-level functions and globals, plus function parameters and local declarations |
| Signature Help | Function signature and active argument for a parsed call |

Text synchronization is full-document. The server ignores stale document versions. LSP character positions use UTF-16 code units, including correct conversion around non-BMP Unicode characters. Cross-file/workspace symbol indexing, rename, semantic highlighting, and incremental parsing are intentionally not claimed in this phase.

### 2. VS Code extension

The extension is under **editors/vscode** and includes:

- .rif language registration.
- TextMate syntax grammar for keywords, types, functions, literals, operators, strings, and comments.
- Bracket pairs, auto-closing, indentation rules, and snippets.
- vscode-languageclient stdio client.
- Configurable rifai.serverPath executable.

Install the Python package into the environment used by VS Code:

~~~bash
python -m pip install -e .
rifai --version
rifai-lsp --version
~~~

The extension defaults to the rifai executable and starts it with the lsp argument. Configure **Rifa'i: Server Path** with the full executable path when VS Code does not inherit the Python environment PATH.

Package the VS Code extension from editors/vscode:

~~~bash
npm install
npm install --global @vscode/vsce
vsce package
~~~

### 3. Compiler pipeline inspection

The command:

~~~bash
rifai inspect examples/hello.rif -o hello.inspect.json
~~~

exports a versioned JSON document (schema_version: 1) containing:

- Lexer tokens, literal values, line/column, and source offsets.
- Structured AST nodes and source spans.
- Global symbols and inferred expression types.
- Bytecode constants, main chunk, function chunks, instruction operands, and source locations.
- Human-readable disassembly and optimization statistics.
- Diagnostics and explicit success/failure state.

The inspection API is also available as **rifai.inspect.inspect_source(...)**. It is designed as the data contract for a future Compiler Explorer / Rifa'i Studio UI, without coupling the compiler to a particular frontend framework.

## Validation

The phase adds unit coverage for LSP initialization, diagnostics, completion, hover, definition, references, document symbols, signature help, UTF-16 positions, stale document versions, JSON-RPC framing, stdio lifecycle, JSON-safe compiler inspection, and optimized/unoptimized snapshots.

The project CI workflow runs the complete Python test suite and the benchmark smoke test. The VS Code extension is shipped as source and is not falsely reported as a marketplace-published package.
