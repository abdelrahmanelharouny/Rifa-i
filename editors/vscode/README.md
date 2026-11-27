# Rifa'i VS Code Extension

This extension adds first-class .rif file support:

- Rifa'i language association and syntax highlighting.
- Bracket matching, automatic closing pairs, and indentation rules.
- Starter snippets for functions, declarations, conditionals, loops, and printing.
- Language Server Protocol integration for diagnostics, completion, hover, go to definition, references, document symbols, and signature help.

## Install the language server

From the repository root, install Rifa'i into the Python environment that VS Code should use:

~~~bash
python -m pip install -e .
~~~

Verify that this environment can run:

~~~bash
rifai --version
rifai-lsp --version
~~~

The extension starts the command configured by **Rifa'i: Server Path** and passes the lsp argument. The default executable is rifai. On Windows, set the setting to the full path of the environment's rifai.exe when it is not available on PATH.

## Build and install the extension

From this directory:

~~~bash
npm install
npm install --global @vscode/vsce
vsce package
~~~

Install the generated VSIX file using **Extensions: Install from VSIX...** in VS Code.

## Development

Open this folder in VS Code and press F5 to launch an Extension Development Host. Open the repository example to exercise the language features. The language server writes protocol traffic only to stdout; diagnostics and unexpected server errors are written to stderr.

The extension is intentionally lightweight: parsing, type checking, symbol resolution, and editor intelligence remain implemented once in the Python compiler frontend.
