# Phase 16 — Advanced Control Flow

## Delivered

- Added reserved keywords and AST nodes for `for`, `break`, and `continue`.
- Added C-style `for` statements with independently optional initializer, condition, and increment clauses.
- Added a dedicated lexical scope for a `for` initializer declaration.
- Added semantic validation for Boolean loop conditions and loop-only `break`/`continue`.
- Added nested-loop-aware IR control-flow targets. A `for`-loop `continue` enters the increment block; a `while`-loop `continue` rechecks its condition.
- Lowered logical `and`/`or` into conditional IR branches with a Boolean block parameter. The right-hand expression is evaluated only when required.
- Reused the existing verified `JUMP` and `JUMP_IF_FALSE` backend. No bytecode opcode or serialized structure was added, so bytecode format v5 and v1-v5 reader compatibility remain unchanged.
- Updated the parser, AST formatter, semantic analyzer, direct AST-to-IR compiler, formal grammar, language specification, README, VS Code syntax highlighting, example, and CI.

## Syntax

~~~rif
for (let index: int = 0; index < 10; index = index + 1) {
    if (index == 3) {
        continue;
    }
    if (index == 8) {
        break;
    }
    print(index);
}

let ready: bool = false and expensive_check();
let cached: bool = true or fetch_value();
~~~

The `for` initializer, condition, and increment may each be omitted. An omitted condition is treated as true, so such a loop normally needs a `break` to terminate. A variable declared in the initializer is visible throughout the loop and is not visible after it.

## Validation

The Phase 16 test module covers syntax and AST shape, loop initializer scope, invalid loop control, Boolean condition validation, nested-loop targets, continue/update behavior, omitted clauses, and short-circuit side-effect and runtime-trap avoidance. CI runs the example through check, run, and inspect as well as the full regression suite.

## Compatibility

The phase adds no bytecode instructions. The emitted modules remain bytecode format v5; legacy bytecode v1-v4 handling is unchanged. Package version: 0.17.0.
