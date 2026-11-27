# Rifa'i VS Code Extension

This extension provides:

- `.rif` file association, syntax highlighting, brackets, indentation, and snippets.
- Language Server Protocol integration for diagnostics, completion, hover, definitions/references, document symbols, and signature help.
- Debug Adapter Protocol integration with source breakpoints, stop-on-entry, continue, step over/into/out, call stack, locals, globals, operand stack, and read-only variable hover/evaluation.
- Debugging for both `.rif` source files and standalone `.rbc` modules.

## Install the Rifa'i runtime

From the repository root, install Rifa'i into the Python environment used by VS Code:

~~~bash
python -m pip install -e .
rifai --version
~~~

The extension uses **Rifa'i: Server Path** for both the language server and debugger. The default is `rifai`. On Windows, set it to the full path of the environment's `rifai.exe` when it is not available on PATH.

## Debug a source file

Open a `.rif` file, select **Run and Debug**, choose **Debug current Rifa'i file**, and press F5. The debugger pauses at entry by default.

You can also create a `.vscode/launch.json` configuration:

~~~json
{
  "version": "0.2.0",
  "configurations": [
    {
      "type": "rifai",
      "request": "launch",
      "name": "Debug Rifa'i",
      "program": "${file}",
      "stopOnEntry": true,
      "noOptimize": false
    }
  ]
}
~~~

Use source breakpoints in the editor, then use the standard VS Code continue, pause, step over, step into, and step out controls. The Variables panel exposes local variables, globals, and the operand stack; the Call Stack panel shows VM frames. Hover/evaluate supports direct variable names only and never executes arbitrary source expressions.

## Debug a standalone bytecode module

Compile a source file first:

~~~bash
rifai compile examples/phase7_debugger.rif
~~~

Then create a launch configuration with `"program": "${workspaceFolder}/examples/phase7_debugger.rbc"`. Bytecode v3 stores the source text and local-symbol names/types, so source breakpoints and named locals continue to work even when the original `.rif` file is moved or unavailable.

Legacy v1/v2 bytecode remains readable and executable. It can be instruction-stepped, but source-level local names are unavailable because those formats did not store debug metadata.

## Build and install the extension

From this directory:

~~~bash
npm install
npm install --global @vscode/vsce
vsce package
~~~

Install the generated VSIX with **Extensions: Install from VSIX...**.

## Development

Open this folder in VS Code and press F5 to launch an Extension Development Host. The Python language server and debug adapter use stdio framing; protocol messages are sent to stdout and diagnostics are sent to stderr.
