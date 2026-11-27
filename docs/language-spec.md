# Rifa'i Language Specification (Version 1.0 — Phase 2)

**Rifa'i** (`.rif`) is a statically typed, imperative, block-structured programming language designed to be compiled by the **Rifa'i Compiler** into a custom stack-based bytecode format (`.rbc`) and executed by the **Rifa'i VM**.

---

## 1. Lexical Structure

### 1.1 Source Encoding and Line Endings
- Source files use the `.rif` extension and are decoded as UTF-8 text.
- Both Unix (`LF`, `\n`) and Windows (`CRLF`, `\r\n`) line endings are supported.
- Line and column numbers are **1-based** (`line >= 1`, `column >= 1`).

### 1.2 Whitespace & Comments
- Whitespace (`' '`, `'\t'`, `'\n'`, `'\r\n'`) separates tokens and is ignored.
- Single-line comments begin with `//` and extend to the end of the line or EOF.
- Block comments (`/* ... */`) are not supported in Version 1.0.

### 1.3 Identifiers & Reserved Keywords
- Identifiers match `[A-Za-z_][A-Za-z0-9_]*`, are case-sensitive, and cannot match reserved keywords:
  `fn`, `let`, `return`, `if`, `else`, `while`, `true`, `false`, `print`, `int`, `float`, `bool`, `string`, `void`, `and`, `or`, `not`.

### 1.4 Literals
- **Integer literals**: `[0-9]+` (e.g., `0`, `42`).
- **Floating-point literals**: `[0-9]+\.[0-9]+` (digits required on both sides of `.`).
- **Boolean literals**: `true`, `false`.
- **String literals**: Single-line double-quoted strings supporting `\"`, `\\`, `\n`, `\t`, `\r`.

---

## 2. Static Type System & Strict Typing

Rifa'i enforces **strict static typing** with **no implicit type conversions**:

| Type | Description | Allowed Contexts |
|---|---|---|
| `int` | Signed integer | Variables, parameters, return types |
| `float` | Floating-point number | Variables, parameters, return types |
| `bool` | Boolean (`true` / `false`) | Variables, parameters, return types |
| `string` | Character string | Variables, parameters, return types |
| `void` | Absence of a return value | Function return type only |
| `T[]` | Homogeneous one-dimensional array of primitive T | Variables, parameters, function returns, indexing |

- `let x: int = 10.5;` and `let y: float = 20;` are both compile-time type errors.
- Variables and function parameters cannot have type `void`.
- Strict compatibility applies equally to variable initialization, reassignment, function arguments, return expressions, and operator operands.

---

## 3. Operator Semantic Rules

### 3.1 Arithmetic Operators
| Operator | Operand Types | Result Type |
|---|---|---|
| `+` | `int + int` | `int` |
| `+` | `float + float` | `float` |
| `+` | `string + string` | `string` (concatenation) |
| `-` | `int - int` / `float - float` | `int` / `float` |
| `*` | `int * int` / `float * float` | `int` / `float` |
| `/` | `int / int` / `float / float` | `float` |
| `%` | `int % int` | `int` |

Mixed `int`/`float` arithmetic, `%` on floats, arithmetic on `bool`, and `-`/`*`/`/`/`%` on `string` are semantic errors. Division by zero is a runtime concern.

### 3.2 Comparison Operators
- **Relational** (`<`, `>`, `<=`, `>=`): Require matching numeric operands (`int` with `int`, or `float` with `float`), yielding `bool`.
- **Equality** (`==`, `!=`): Require matching value types (`int`, `float`, `bool`, or `string`), yielding `bool`.

### 3.3 Logical & Unary Operators
- **Logical** (`and`, `or`): Require `bool` operands and yield `bool`.
- **Unary `-`**: Accepts `int` or `float` and returns the same type.
- **Unary `not`**: Accepts `bool` and returns `bool`.

---

## 4. Variables, Scopes, and Shadowing

1. Every variable declaration requires an explicit type annotation and an initializer (`let name: type = expr;`).
2. Assignment (`name = expr;`) is a **statement**, not an expression.
3. Variables must be declared before they are read or reassigned (no variable hoisting).
4. Duplicate declarations in the same scope are forbidden.
5. Child block scopes (`{ ... }`, `if`, `else`, `while`) may shadow outer variables; scope lookup resolves the nearest enclosing declaration.
6. Variables declared inside a block are not visible outside that block.
7. Function parameters and declarations in the function's outermost body share the function scope, so parameters cannot be redeclared directly in the function body.

---

## 5. Functions & Return Validation

- Functions must be declared at the top level (`fn name(p1: T1, ...) -> R { ... }`); nested function declarations are rejected.
- Function signatures are registered in a global pre-pass, enabling **recursion**, **mutual recursion**, and **forward references**.
- Function names and global variable names share the global namespace and cannot collide; function overloading is not supported.
- Function calls verify that the callee is a function, argument counts match, and every argument matches its parameter type. Calling a `void` function where a value is required is a semantic error; standalone `ExpressionStatement` calls (`foo();`) are allowed.
- **Return rules**:
  - Top-level `return` statements are invalid.
  - `void` functions allow `return;` or falling through, and forbid `return expr;`.
  - Non-`void` functions require `return expr;` matching the declared return type, and **every execution path must definitely return** (an unconditional `return`, a block containing a definitely-returning statement, or an `if`/`else` where both branches definitely return; `while` loops never count as guaranteed to return).

---

## 6. Control Flow, Conditions, and Printing

- `if (cond)` and `while (cond)` require `cond` to have type `bool`.
- `print(expr);` accepts any non-`void` value (`int`, `float`, `bool`, `string`).

---

## 7. Expression Precedence

From highest to lowest:
1. Primary & calls: literals, identifiers, `fn_call(args...)`, `(expr)`
2. Unary (right-associative prefix): `-`, `not`
3. Multiplicative (left-associative): `*`, `/`, `%`
4. Additive (left-associative): `+`, `-`
5. Relational (left-associative): `<`, `>`, `<=`, `>=`
6. Equality (left-associative): `==`, `!=`
7. Logical AND (left-associative): `and`
8. Logical OR (left-associative): `or`


## 8. Logical Evaluation

The version 1 language evaluates both operands of the logical operators and and or before applying the logical operation. These operators are eager, not short-circuiting. This is consistent with the version 1 bytecode AND and OR instructions. A future language version may introduce short-circuit semantics only with an explicit specification and bytecode compatibility decision.


## 9. Typed Arrays and Collection Operations

Rifa'i supports one-dimensional homogeneous arrays with element type int, float, bool, or string. Type annotations use int[], float[], bool[], or string[]. Array literals use square brackets, for example [1, 2, 3], [true, false], or ["a", "b"].

A non-empty literal infers its element type from its first element and requires every later element to have exactly the same type. An empty literal ([]) requires an explicit array type context, such as let values: int[] = []. Nested arrays and implicit element conversions are not supported.

Arrays can be passed to and returned from functions. They are reference values: assigning one array variable to another creates an alias, not a copy. Indexes are zero-based and must have type int. Reads and writes outside the valid range are runtime errors.

Standard collection functions:
- len(string) -> int and len(T[]) -> int.
- push(T[], T) -> void appends an element matching the array's declared element type.
- pop(T[]) -> T removes and returns the final element; an empty pop is a runtime error.

The names len, push, and pop are reserved for the standard library and cannot be declared as variables or user functions. The VM enforces runtime element types, index bounds, non-empty pop, and the configurable max_array_items resource limit, including for untrusted bytecode.
