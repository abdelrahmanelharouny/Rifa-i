# Phase 7 — Debugging Toolchain

## Delivery overview

Phase 7 now provides a complete source-aware debugging workflow through both the command line and Visual Studio Code. The same verified VM, immutable instruction snapshots, source maps, breakpoint rules, and stepping semantics power both interfaces.

## Standalone bytecode debug metadata

Bytecode format version 3 adds an optional `debug_info` payload:
- Embedded source text, allowing the editor/debug adapter to display the original source when the `.rif` file is unavailable.
- Per-chunk local-symbol tables mapping zero-based slots to source identifiers and static types.
- Verifier checks for metadata structure, code-chunk references, duplicate entries/slots, valid types, and in-range local slots.

Compiler-produced modules populate this metadata automatically. The optimizer preserves it because local slots are not renumbered. Serialization is deterministic and remains subject to the 16 MiB whole-file limit and an 8 Mi-character embedded-source cap.

### Compatibility

- v1: original single main chunk; remains readable and writable.
- v2: function table and CALL/RETURN; remains readable and writable.
- v3: function table plus optional source/local debug metadata; is the compiler's default output.

Older v1/v2 modules still run and can be instruction-stepped. They cannot recover source-level local names that were never stored in the file; the debugger falls back to numbered slots. New v3 `.rbc` files can be debugged after their original `.rif` file is removed.

## CLI debugger

Start a source debugging session:

~~~bash
rifai debug examples/phase7_debugger.rif --breakpoint 4
~~~

Or compile and debug a standalone bytecode file:

~~~bash
rifai compile examples/phase7_debugger.rif
rifai debug examples/phase7_debugger.rbc
~~~

The interactive debugger supports entry pause, source breakpoints, continue, step into/over/out, one-bytecode-instruction stepping, locals, globals, operand stack, call-stack backtraces, nearby source, and current-instruction inspection. It validates requested breakpoints against executable source-mapped lines.

## Visual Studio Code Debug Adapter Protocol

The Python adapter is launched over stdio with:

~~~bash
rifai debug-adapter
~~~

The extension contributes a `rifai` launch type and starts that adapter using the configured **Rifa'i: Server Path** executable. Open a `.rif` file, select **Debug current Rifa'i file**, and press F5. A checked-in or user launch configuration can also point to an `.rbc` file.

Implemented DAP requests/events include:
- Initialization and launch/configuration handshake.
- Source line breakpoints, verified against executable source-map lines.
- Entry stops, continue, pause, step over, step into, and step out.
- Thread list, stack traces, source references/loaded source retrieval.
- Locals, globals, and operand-stack scopes with typed values.
- Read-only hover/evaluate for a direct variable name.
- Output, exited, terminated, and stopped/continued events.
- Terminate and disconnect handling.

The adapter runs the VM on a worker thread so the protocol loop remains responsive while execution is paused. DAP framing and outbound sequence numbers are handled centrally; protocol diagnostics never contaminate stdout.

Arbitrary expression evaluation, conditional breakpoints, function breakpoints, and variable mutation are intentionally not advertised or implemented. The evaluate request resolves only a direct local/global variable identifier and never executes source text.

## Validation

Automated coverage includes:
- v3 serialization round trips, embedded source and local-symbol preservation, metadata verification, and optimizer preservation.
- v2 compatibility read/write/execution and existing v1 compatibility tests.
- CLI debugging of an `.rbc` after deleting the original `.rif`.
- DAP stdio framing, initialize/launch, source breakpoints, entry pause, stack frames, scopes, variables, embedded-source retrieval, continue, termination, and disconnect.
- VS Code extension manifest validation, including debugger contribution registration.

The repository CI runs the complete pytest suite on Python 3.11.
