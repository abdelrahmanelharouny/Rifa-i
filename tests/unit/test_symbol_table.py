"""Unit tests for the Rifa'i SymbolTable and Scope management."""

from __future__ import annotations

import pytest

from rifai.frontend.ast_nodes import SourceSpan
from rifai.frontend.symbol_table import (
    FunctionSymbol,
    SymbolKind,
    SymbolTable,
    VariableSymbol,
)
from rifai.frontend.types import RifaiType

_SPAN = SourceSpan(line=1, column=1, start_offset=0, end_offset=1)


def _var(name: str, rifai_type: RifaiType, depth: int, *, is_param: bool = False) -> VariableSymbol:
    return VariableSymbol(
        name=name,
        rifai_type=rifai_type,
        declaration_span=_SPAN,
        is_parameter=is_param,
        is_global=(depth == 0),
        scope_depth=depth,
    )


def test_global_and_local_scope_resolution_and_shadowing() -> None:
    table = SymbolTable()
    outer_x = _var("x", RifaiType.INT, 0)
    assert table.define_variable(outer_x)
    assert table.resolve("x") is outer_x

    table.enter_scope("block")
    assert table.current_scope.depth == 1
    assert table.resolve("x") is outer_x

    inner_x = _var("x", RifaiType.STRING, 1)
    assert table.define_variable(inner_x)
    assert table.resolve("x") is inner_x
    assert table.resolve_local("x") is inner_x

    table.exit_scope()
    assert table.current_scope.depth == 0
    assert table.resolve("x") is outer_x


def test_duplicate_declaration_in_same_scope_is_rejected() -> None:
    table = SymbolTable()
    assert table.define_variable(_var("a", RifaiType.INT, 0))
    assert not table.define_variable(_var("a", RifaiType.FLOAT, 0))


def test_function_and_parameter_registration_and_scope_exit() -> None:
    table = SymbolTable()
    param = _var("n", RifaiType.INT, 1, is_param=True)
    fn_sym = FunctionSymbol(
        name="square",
        params=(param,),
        return_type=RifaiType.INT,
        declaration_span=_SPAN,
    )
    assert fn_sym.kind is SymbolKind.FUNCTION
    assert param.kind is SymbolKind.PARAMETER
    assert table.define_function(fn_sym)
    assert not table.define_function(fn_sym)

    table.enter_scope("fn:square")
    assert table.define_variable(param)
    assert table.resolve("n") is param
    assert table.resolve("square") is fn_sym
    table.exit_scope()

    assert table.resolve("n") is None
    assert table.resolve("square") is fn_sym


def test_exiting_global_scope_raises() -> None:
    table = SymbolTable()
    with pytest.raises(RuntimeError):
        table.exit_scope()
