"""Symbol table and lexical scope management for Rifa'i."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from rifai.frontend.ast_nodes import SourceSpan
from rifai.frontend.types import RifaiType


class SymbolKind(str, Enum):
    """Kind of declared symbol in a Rifa'i scope."""

    VARIABLE = "variable"
    PARAMETER = "parameter"
    FUNCTION = "function"


@dataclass(frozen=True, slots=True)
class VariableSymbol:
    """Symbol metadata for a variable or function parameter."""

    name: str
    rifai_type: RifaiType
    declaration_span: SourceSpan
    is_parameter: bool
    is_global: bool
    scope_depth: int

    @property
    def kind(self) -> SymbolKind:
        return SymbolKind.PARAMETER if self.is_parameter else SymbolKind.VARIABLE


@dataclass(frozen=True, slots=True)
class FunctionSymbol:
    """Symbol metadata for a top-level function declaration."""

    name: str
    params: tuple[VariableSymbol, ...]
    return_type: RifaiType
    declaration_span: SourceSpan

    @property
    def kind(self) -> SymbolKind:
        return SymbolKind.FUNCTION


Symbol = VariableSymbol | FunctionSymbol


class Scope:
    """Single lexical scope linked to an optional enclosing parent scope."""

    def __init__(
        self,
        name: str,
        depth: int,
        parent: Scope | None = None,
    ) -> None:
        self.name = name
        self.depth = depth
        self.parent = parent
        self._symbols: dict[str, Symbol] = {}

    @property
    def symbols(self) -> dict[str, Symbol]:
        """Return a shallow copy of symbols declared directly in this scope."""
        return dict(self._symbols)

    def define(self, symbol: Symbol) -> bool:
        """Register `symbol` in this scope; return False if name already exists here."""
        if symbol.name in self._symbols:
            return False
        self._symbols[symbol.name] = symbol
        return True

    def resolve_local(self, name: str) -> Symbol | None:
        """Look up `name` only in this scope."""
        return self._symbols.get(name)

    def resolve(self, name: str) -> Symbol | None:
        """Look up `name` in this scope or nearest enclosing ancestor scope."""
        current: Scope | None = self
        while current is not None:
            found = current._symbols.get(name)
            if found is not None:
                return found
            current = current.parent
        return None


class SymbolTable:
    """Manages lexical scopes for Rifa'i semantic analysis."""

    def __init__(self) -> None:
        self._global_scope = Scope(name="global", depth=0, parent=None)
        self._current_scope = self._global_scope

    @property
    def global_scope(self) -> Scope:
        """Return the root global scope."""
        return self._global_scope

    @property
    def current_scope(self) -> Scope:
        """Return the currently active innermost scope."""
        return self._current_scope

    def enter_scope(self, name: str = "block") -> Scope:
        """Push and return a new child scope."""
        child = Scope(
            name=name,
            depth=self._current_scope.depth + 1,
            parent=self._current_scope,
        )
        self._current_scope = child
        return child

    def exit_scope(self) -> Scope:
        """Pop the current scope and return to its parent."""
        if self._current_scope.parent is None:
            raise RuntimeError("Cannot exit the global scope.")
        exited = self._current_scope
        self._current_scope = self._current_scope.parent
        return exited

    def define_variable(self, symbol: VariableSymbol) -> bool:
        """Define a variable or parameter in the current scope."""
        return self._current_scope.define(symbol)

    def define_function(self, symbol: FunctionSymbol) -> bool:
        """Define a function in the global scope."""
        return self._global_scope.define(symbol)

    def resolve(self, name: str) -> Symbol | None:
        """Resolve `name` from the current scope outward."""
        return self._current_scope.resolve(name)

    def resolve_local(self, name: str) -> Symbol | None:
        """Resolve `name` strictly within the current scope."""
        return self._current_scope.resolve_local(name)
