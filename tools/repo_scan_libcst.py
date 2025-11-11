"""LibCST-powered import/export analysis helpers."""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import libcst as cst
    from libcst import ParserSyntaxError
    from libcst import matchers as m
except ImportError:  # pragma: no cover - optional dependency at runtime
    cst = None  # type: ignore[assignment]
    ParserSyntaxError = Exception  # type: ignore[assignment]
    m = None

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    import libcst as libcst_types
else:  # pragma: no cover - typing-only shim
    libcst_types = cst if cst is not None else Any


@dataclass(slots=True, frozen=True)
class CSTImports:
    """Structured import/export information for a module."""

    file: str
    module: str
    imports: tuple[str, ...]  # absolute and normalized
    tc_imports: tuple[str, ...]  # those under `if TYPE_CHECKING`
    exports: tuple[str, ...]  # names in __all__ (best-effort)
    star_imports: tuple[str, ...]  # from pkg import *
    has_parse_errors: bool = False


def _resolve_relative(module_name: str, level: int, attr: str | None) -> str | None:
    """Mimic runtime import name resolution without executing imports.

    Returns
    -------
    str | None
        Absolute module path or ``None`` when resolution fails.
    """
    try:
        base = "." * level + (attr or "")
        return importlib.util.resolve_name(base, module_name)
    except (ImportError, ValueError):
        return None


if cst is not None:

    class ImportCollector(cst.CSTVisitor):
        """Collect imports/exports from a LibCST module."""

        def __init__(self, module_name: str) -> None:
            self.module_name = module_name
            self.imports: set[str] = set()
            self.type_checking_imports: set[str] = set()
            self.star_imports: set[str] = set()
            self.exports: set[str] = set()
            self._type_check_guard_depth = 0

        @staticmethod
        def _is_type_check_guard(test: libcst_types.BaseExpression) -> bool:
            if m is None:
                return False
            return bool(
                m.matches(test, m.Name("TYPE_CHECKING"))
                or m.matches(
                    test, m.Attribute(value=m.Name("typing"), attr=m.Name("TYPE_CHECKING"))
                )
            )

        def visit_If(self, node: libcst_types.If) -> bool | None:  # noqa: N802
            """Track entry into TYPE_CHECKING guard blocks.

            Returns
            -------
            bool | None
                ``True`` to continue traversal.
            """
            if self._is_type_check_guard(node.test):
                self._type_check_guard_depth += 1
            return True

        def leave_If(self, original_node: libcst_types.If) -> None:  # noqa: N802
            """Track exit from TYPE_CHECKING guard blocks."""
            if self._is_type_check_guard(original_node.test):
                self._type_check_guard_depth = max(0, self._type_check_guard_depth - 1)

        def visit_Import(self, node: libcst_types.Import) -> bool | None:  # noqa: N802
            """Record modules imported via ``import ...``.

            Returns
            -------
            bool | None
                ``True`` to continue traversal.
            """
            for alias in node.names:
                asname = getattr(alias, "asname", None)
                target_node = getattr(asname, "name", None) if asname else None
                target = getattr(target_node, "value", None) if target_node else None
                canonical = self._import_root(alias.name)
                import_name = target or canonical
                if import_name:
                    self._add_import(import_name)
            return True

        def visit_ImportFrom(self, node: libcst_types.ImportFrom) -> bool | None:  # noqa: N802
            """Record modules imported via ``from ... import ...``.

            Returns
            -------
            bool | None
                ``True`` to continue traversal.
            """
            module_name = self._absolute_from_module(node)
            aliases = self._coerce_aliases(node.names)
            self._record_from_aliases(module_name, aliases)
            return True

        def visit_Assign(self, node: libcst_types.Assign) -> bool | None:  # noqa: N802
            """Capture ``__all__`` literal assignments.

            Returns
            -------
            bool | None
                ``True`` to continue traversal.
            """
            if not self._assigns_dunder_all(node):
                return True
            for export in self._literal_string_values(node.value):
                self.exports.add(export)
            return True

        def _add_import(self, module: str) -> None:
            """Record an import edge, tracking TYPE_CHECKING context."""
            target = self.type_checking_imports if self._type_check_guard_depth else self.imports
            target.add(module)

        @staticmethod
        def _import_root(name: libcst_types.BaseExpression) -> str | None:
            """Return the absolute module string represented by ``name``.

            Returns
            -------
            str | None
                Fully-qualified module path if resolvable.
            """
            if isinstance(name, libcst_types.Attribute):
                parts: list[str] = []
                current: libcst_types.Attribute | libcst_types.BaseExpression = name
                while isinstance(current, libcst_types.Attribute):
                    attr = current.attr
                    if isinstance(attr, libcst_types.Name):
                        parts.append(attr.value)
                    current = current.value
                if isinstance(current, libcst_types.Name):
                    parts.append(current.value)
                return ".".join(reversed(parts)) if parts else None
            if isinstance(name, libcst_types.Name):
                return name.value
            return None

        def _absolute_from_module(self, node: libcst_types.ImportFrom) -> str | None:
            """Resolve the absolute module for a ``from`` import.

            Returns
            -------
            str | None
                Absolute module path or ``None`` when resolution fails.
            """
            module_attr: str | None = None
            if node.module:
                module_attr = self._import_root(node.module)
            level = len(node.relative) if node.relative else 0
            if level:
                return _resolve_relative(self.module_name, level, module_attr)
            return module_attr

        def _record_from_aliases(
            self,
            module_name: str | None,
            aliases: list[libcst_types.ImportAlias | libcst_types.ImportStar],
        ) -> None:
            """Record import targets for a ``from`` statement."""
            for alias in aliases:
                if isinstance(alias, libcst_types.ImportStar):
                    if module_name:
                        self.star_imports.add(module_name)
                    continue
                imported = self._import_root(alias.name)
                if imported is None:
                    continue
                symbol = f"{module_name}.{imported}" if module_name else imported
                root = symbol.strip(".")
                if root:
                    self._add_import(root)

        @staticmethod
        def _coerce_aliases(
            names: Sequence[libcst_types.ImportAlias] | libcst_types.ImportStar,
        ) -> list[libcst_types.ImportAlias | libcst_types.ImportStar]:
            """Return a list of import aliases regardless of LibCST representation.

            Returns
            -------
            list[libcst_types.ImportAlias | libcst_types.ImportStar]
                Imported symbols normalized to a list.
            """
            if isinstance(names, Sequence):
                return list(names)
            return [names]

        @staticmethod
        def _assigns_dunder_all(node: libcst_types.Assign) -> bool:
            """Return ``True`` when the assignment targets ``__all__``.

            Returns
            -------
            bool
                ``True`` if any target references ``__all__``.
            """
            if m is None:
                return False
            return any(m.matches(target.target, m.Name("__all__")) for target in node.targets)

        @staticmethod
        def _literal_string_values(expr: libcst_types.BaseExpression) -> Iterable[str]:
            """Return literal string values from list/tuple expressions.

            Returns
            -------
            Iterable[str]
                Extracted strings or an empty tuple when ``expr`` is not a literal sequence.
            """
            if cst is None or not isinstance(expr, (cst.List, cst.Tuple)):
                return ()
            exports: list[str] = []
            for element in expr.elements:
                if not element or not isinstance(element.value, cst.SimpleString):
                    continue
                try:
                    text = element.value.evaluated_value
                except (ValueError, TypeError):  # pragma: no cover - defensive
                    continue
                if isinstance(text, str):
                    exports.append(text)
            return tuple(exports)


else:
    ImportCollector = None  # type: ignore[assignment]


def collect_imports_with_libcst(path: Path, module_name: str) -> CSTImports:
    """
    Parse a file with LibCST and extract import/export info.

    Returns
    -------
    CSTImports
        Normalized import summary for the requested module.
    """
    if cst is None:
        return CSTImports(str(path), module_name, (), (), (), (), has_parse_errors=True)

    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        LOGGER.debug("Unable to read %s: %s", path, exc)
        return CSTImports(str(path), module_name, (), (), (), (), has_parse_errors=True)

    try:
        module = cst.parse_module(src)
    except ParserSyntaxError as exc:
        LOGGER.debug("LibCST parse error for %s: %s", path, exc)
        return CSTImports(str(path), module_name, (), (), (), (), has_parse_errors=True)

    if ImportCollector is None:
        return CSTImports(str(path), module_name, (), (), (), (), has_parse_errors=True)

    collector = ImportCollector(module_name)
    module.visit(collector)

    return CSTImports(
        file=str(path),
        module=module_name,
        imports=tuple(sorted(collector.imports)),
        tc_imports=tuple(sorted(collector.type_checking_imports)),
        exports=tuple(sorted(collector.exports)),
        star_imports=tuple(sorted(collector.star_imports)),
        has_parse_errors=False,
    )
