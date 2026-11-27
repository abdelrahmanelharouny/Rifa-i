# Phase 7 — Interactive Debugger

## Delivery overview

Phase 7 adds an interactive, source-aware debugger on top of the existing verified Rifa'i VM. It does not alter the instruction set, bytecode wire format, serializer, or existing execution semantics.

Start a debugging session with:

~~~bash
rifai debug examples/phase7_debugger.rif
~~~

Initial source breakpoints can be supplied repeatedly:

~~~bash
rifai debug examples/phase7_debugger.rif --breakpoint 8 --breakpoint 15
~~~

The debugger pauses before the first instruction and presents the current source location, function, opcode, instruction index, call depth, and executed-instruction count.

## Execution controls

| Command | Behavior |
|---|---|
| continue / c | Continue until a configured breakpoint |
| step / s | Step into the next source expression or function call |
| next / n | Step over the current source expression or call |
| out / finish | Continue until the active function returns |
| stepi | Execute one bytecode instruction |
| break line | Add a source-line breakpoint interactively |
| delete line | Remove a source-line breakpoint |
| breakpoints | List configured breakpoints |
| quit / q | Stop debugging without finishing execution |

Breakpoints are source-line based and pause before the first instruction mapped to that line on each visit. Multiple bytecode instructions on one source line do not cause repeated stops during the same visit. A loop that returns to the line triggers the breakpoint again.

## Runtime inspection

At every pause, the debugger can inspect:

- **Locals:** source-level variable names, static types, slot indices, values, and uninitialized state for the current frame.
- **Globals:** global variables and current values.
- **Operand stack:** values from bottom to top.
- **Call stack:** active function frames, instruction pointers, and current source location.
- **Source:** a configurable neighborhood around the current statement.
- **Current instruction:** opcode, operand, chunk name, instruction index, and source mapping.

The VM exposes immutable snapshots through the optional on_instruction callback. Existing callers that do not provide this callback retain the previous execution behavior.

## Debug metadata and compatibility

The compiler records a transient mapping from local slots to source variable names and types in CompilationResult.debug_symbols. The debugger uses that metadata to make local inspection meaningful. It is intentionally not added to CodeChunk or serialized .rbc modules, so bytecode v1/v2 compatibility and the existing file format remain unchanged.

For that reason, rifai debug currently accepts .rif source files and compiles them in the current process. It does not claim source-level names when debugging a standalone .rbc file. Use --no-optimize when you want stepping to follow the direct code-generator instruction sequence rather than optimized instructions.

The debugger retains all existing VM limits and validation. Runtime errors remain source-aware and are reported with the original file path.

## Validation

New tests cover observer snapshot parity, source-level local metadata, call-frame inspection, step-into/over/out decisions, one-stop-per-line breakpoint behavior, interactive inspection commands, early abort, and the CLI. CI also runs a scripted debugger smoke test against a real .rif example.
