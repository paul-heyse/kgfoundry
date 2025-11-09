"""Apply rendered docstrings to source files using LibCST."""

from __future__ import annotations

import ast
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import libcst as cst

from kgfoundry_common.errors import ConfigurationError
from tools.docstring_builder.config_models import DocstringApplyConfig

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from libcst import (
        BaseSmallStatement,
        BaseStatement,
        FlattenSentinel,
        RemovalSentinel,
    )

    from tools.docstring_builder.harvest import HarvestResult
    from tools.docstring_builder.schema import DocstringEdit


def _escape_docstring(text: str, indent: str) -> str:
    normalized = text.replace("\r\n", "\n").rstrip("\n")
    escaped = normalized.replace('"""', '\\"""')
    if not escaped:
        return "\n"
    lines = escaped.split("\n")
    if len(lines) == 1:
        return f"{lines[0]}\n"
    summary, *rest = lines
    indented_rest = [
        (
            f"{indent}{line}" if line else ""
        )  # Preserve blank lines without trailing spaces
        for line in rest
    ]
    joined = "\n".join([summary, *indented_rest])
    return f"{joined}\n"


def _thaw(instance: object, **updates: object) -> None:
    """Mutate frozen dataclass instances safely."""
    for name, value in updates.items():
        _SETATTR(instance, name, value)


@dataclass(slots=True, frozen=True)
class _DocstringTransformer(cst.CSTTransformer):
    module_name: str
    edits: Mapping[str, DocstringEdit]
    changed: bool = False
    namespace: list[str] = field(default_factory=list, init=False, repr=False)

    def _qualify(self, name: str) -> str:
        if self.namespace:
            pieces = [self.module_name, *self.namespace[:-1], name]
        else:
            pieces = [self.module_name, name]
        return ".".join(piece for piece in pieces if piece)

    def _inject_docstring(
        self, node: cst.FunctionDef | cst.ClassDef, qname: str
    ) -> tuple[cst.ClassDef | cst.FunctionDef, bool]:
        edit = self.edits.get(qname)
        if not edit:
            return node, False
        indent_level = max(len(self.namespace), 1)
        desired = _escape_docstring(edit.text, " " * 4 * indent_level)
        literal = cst.SimpleString(f'"""{desired}"""')
        expr = cst.Expr(value=literal)
        docstring_stmt = cst.SimpleStatementLine(body=(expr,))

        body = node.body
        original_statements = cast(
            "Sequence[cst.BaseStatement | BaseSmallStatement]", body.body
        )

        def _as_statement(
            item: cst.BaseStatement | BaseSmallStatement,
        ) -> cst.BaseStatement:
            if isinstance(item, cst.BaseStatement):
                return item
            return cst.SimpleStatementLine(body=(item,))

        existing_statements: list[cst.BaseStatement] = [
            _as_statement(stmt) for stmt in original_statements
        ]

        if existing_statements and isinstance(
            existing_statements[0], cst.SimpleStatementLine
        ):
            first = existing_statements[0]
            if (
                first.body
                and isinstance(first.body[0], cst.Expr)
                and isinstance(first.body[0].value, cst.SimpleString)
            ):
                current_value = cast("str", ast.literal_eval(first.body[0].value.value))
                if current_value == desired:
                    return node, False
                new_statements: list[cst.BaseStatement] = [
                    docstring_stmt,
                    *existing_statements[1:],
                ]
            else:
                new_statements = [docstring_stmt, *existing_statements]
        else:
            new_statements = [docstring_stmt, *existing_statements]

        if new_statements == existing_statements:
            return node, False
        new_body = body.with_changes(
            body=cast("tuple[cst.BaseStatement, ...]", tuple(new_statements))
        )
        return node.with_changes(body=new_body), True

    def visit_classdef(self, node: cst.ClassDef) -> bool:
        """Visit class definition and track namespace.

        Parameters
        ----------
        node : cst.ClassDef
            ClassDef CST node.

        Returns
        -------
        bool
            True to continue visiting children.
        """
        self.namespace.append(node.name.value)
        return True

    def leave_classdef(
        self, _original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> BaseStatement | FlattenSentinel[BaseStatement] | RemovalSentinel:
        """Leave class definition and inject docstring.

        Parameters
        ----------
        _original_node : cst.ClassDef
            Original CST node (unused).
        updated_node : cst.ClassDef
            Updated CST node.

        Returns
        -------
        BaseStatement | FlattenSentinel[BaseStatement] | RemovalSentinel
            Transformed node with docstring injected.
        """
        qname = self._qualify(updated_node.name.value)
        self.namespace.pop()
        transformed_node, changed = self._inject_docstring(updated_node, qname)
        if changed:
            _thaw(self, changed=True)
        return cast("BaseStatement", transformed_node)

    def visit_functiondef(self, node: cst.FunctionDef) -> bool:
        """Visit function definition and track namespace.

        Parameters
        ----------
        node : cst.FunctionDef
            FunctionDef CST node.

        Returns
        -------
        bool
            True to continue visiting children.
        """
        self.namespace.append(node.name.value)
        return True

    def leave_functiondef(
        self, _original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> BaseStatement | FlattenSentinel[BaseStatement] | RemovalSentinel:
        """Leave function definition and inject docstring.

        Parameters
        ----------
        _original_node : cst.FunctionDef
            Original CST node (unused).
        updated_node : cst.FunctionDef
            Updated CST node.

        Returns
        -------
        BaseStatement | FlattenSentinel[BaseStatement] | RemovalSentinel
            Transformed node with docstring injected.
        """
        qname = self._qualify(updated_node.name.value)
        self.namespace.pop()
        transformed_node, changed = self._inject_docstring(updated_node, qname)
        if changed:
            _thaw(self, changed=True)
        return cast("BaseStatement", transformed_node)


def _atomic_write(target: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Persist content atomically, replacing the target file.

    Parameters
    ----------
    target : Path
        Target file path.
    content : str
        Content to write.
    encoding : str, optional
        File encoding. Defaults to "utf-8".

    Raises
    ------
    ConfigurationError
        If the temporary file cannot be created or the atomic write fails.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=target.parent,
            delete=False,
        ) as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            temp_name = tmp_file.name
        if not temp_name:
            message = "Atomic write failed to materialize temporary file"
            raise ConfigurationError(
                message,
                context={
                    "target_path": str(target),
                    "encoding": encoding,
                },
            )
        temp_path = Path(temp_name)
        temp_path.replace(target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def apply_edits(
    result: HarvestResult,
    edits: Iterable[DocstringEdit],
    *,
    apply_config: DocstringApplyConfig | None = None,
) -> tuple[bool, str | None]:
    """Apply docstring edits to the harvested file.

    Parameters
    ----------
    result : HarvestResult
        The harvested module metadata, including the target filepath.
    edits : Iterable[DocstringEdit]
        The sequence of docstring edits to apply to the module.
    apply_config : DocstringApplyConfig | None, optional
        Configuration controlling whether edits are written, whether backups are created,
        and whether atomic writes are used. Defaults to ``DocstringApplyConfig()``.

    Returns
    -------
    tuple[bool, str | None]
        A tuple ``(changed, code)`` where ``changed`` indicates whether any docstrings were
        updated. The ``code`` element contains the rendered module when the configuration runs
        in dry-run mode (``write_changes=False``); otherwise, it is ``None``.
    """
    config = apply_config or DocstringApplyConfig()
    mapping = {edit.qname: edit for edit in edits}
    if not mapping:
        return False, None
    original = result.filepath.read_text(encoding="utf-8")
    module = cst.parse_module(original)
    transformer = _DocstringTransformer(module_name=result.module, edits=mapping)
    new_module = module.visit(transformer)
    code = new_module.code
    if transformer.changed and config.write_changes:
        if config.create_backups:
            backup_path = result.filepath.with_name(f"{result.filepath.name}.bak")
            backup_path.write_text(original, encoding="utf-8")
        if config.atomic_writes:
            _atomic_write(result.filepath, code)
        else:
            result.filepath.write_text(code, encoding="utf-8")
    preview: str | None = None
    if not config.write_changes:
        preview = code
    return transformer.changed, preview


__all__ = ["apply_edits"]
_SETATTR = object.__setattr__
