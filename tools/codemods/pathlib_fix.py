"""Codemod to convert os.path and os.makedirs to pathlib.Path.

This script uses LibCST to transform common filesystem operations:
- os.makedirs() → Path.mkdir(parents=True)
- os.path.join() → Path / operator
- open(os.path.join(...)) → Path.open()
- os.path.exists() → Path.exists()
- os.path.dirname() → Path.parent

Requirement: R1 — Pathlib Standardization Across Workflows
Scenario: Index writer uses Path helpers
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import libcst as cst

if TYPE_CHECKING:
    from collections.abc import Sequence

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PathlibArgs:
    """Parsed CLI options for the pathlib codemod."""

    targets: tuple[Path, ...]
    dry_run: bool
    log: Path | None


def _parse_args(argv: Sequence[str] | None = None) -> PathlibArgs:
    parser = argparse.ArgumentParser(
        description="Convert os.path operations to pathlib.Path",
    )
    parser.add_argument(
        "targets",
        nargs="+",
        type=Path,
        help="Files or directories to transform",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without modifying files",
    )
    parser.add_argument(
        "--log",
        type=Path,
        help="Write change log to file",
    )

    parsed: argparse.Namespace = parser.parse_args(argv)
    targets = tuple(cast("list[Path]", parsed.targets))
    log_path = cast("Path | None", parsed.log)
    dry_run = bool(cast("bool", parsed.dry_run))
    return PathlibArgs(targets=targets, dry_run=dry_run, log=log_path)


def _is_os_call(expression: cst.BaseExpression, *, name: str) -> bool:
    return (
        isinstance(expression, cst.Attribute)
        and isinstance(expression.value, cst.Name)
        and expression.value.value == "os"
        and expression.attr.value == name
    )


def _is_os_path_call(expression: cst.BaseExpression, *, name: str) -> bool:
    return (
        isinstance(expression, cst.Attribute)
        and isinstance(expression.value, cst.Attribute)
        and isinstance(expression.value.value, cst.Name)
        and expression.value.value.value == "os"
        and expression.value.attr.value == "path"
        and expression.attr.value == name
    )


def _is_name(node: cst.BaseExpression, value: str) -> bool:
    return isinstance(node, cst.Name) and node.value == value


MIN_PATH_PARTS = 2


def _path_join_expression(arguments: Sequence[cst.Arg]) -> cst.BaseExpression | None:
    pos_args = [arg for arg in arguments if arg.keyword is None]
    if len(pos_args) < MIN_PATH_PARTS:
        return None
    base = cst.Call(
        func=cst.Name("Path"),
        args=(cst.Arg(pos_args[0].value),),
    )
    result: cst.BaseExpression = base
    for arg in pos_args[1:]:
        result = cst.BinaryOperation(
            left=result,
            operator=cst.Divide(),
            right=arg.value,
        )
    return result


class PathlibTransformer(cst.CSTTransformer):
    """Apply pathlib conversions to common ``os.path`` call sites.

    Initializes transformer with change tracking.
    """

    def __init__(self) -> None:
        super().__init__()
        self.changes: list[str] = []
        self.needs_pathlib_import: bool = False

    def on_visit(self, node: cst.CSTNode) -> bool:
        """Track if pathlib import already exists.

        Parameters
        ----------
        node : cst.CSTNode
            Node being visited.

        Returns
        -------
        bool
            True to continue traversal.
        """
        if isinstance(node, cst.Import):
            for alias in node.names:
                if isinstance(alias.name, cst.Name) and alias.name.value == "pathlib":
                    self.needs_pathlib_import = True
        return True

    def leave_call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        """Apply call rewrites when exiting a Call node.

        Parameters
        ----------
        original_node : cst.Call
            Original call node.
        updated_node : cst.Call
            Updated call node.

        Returns
        -------
        cst.BaseExpression
            Transformed call expression.
        """
        replacement = self._transform_call(original_node)
        return replacement if replacement is not None else updated_node

    def leave_with(self, original_node: cst.With, updated_node: cst.With) -> cst.With:
        """Apply with-statement rewrites when exiting a ``with`` block.

        Parameters
        ----------
        original_node : cst.With
            Original with statement node before transformation.
        updated_node : cst.With
            Updated with statement node after child transformations.

        Returns
        -------
        cst.With
            Potentially transformed with statement node.
        """
        return self._transform_with(original_node, updated_node)

    leave_Call = leave_call  # noqa: N815 - LibCST requires CamelCase visitor names
    leave_With = leave_with  # noqa: N815 - LibCST requires CamelCase visitor names

    def _transform_makedirs(self, node: cst.Call) -> cst.BaseExpression | None:
        if not (
            isinstance(node.func, cst.Attribute)
            and _is_os_call(node.func, name="makedirs")
            and node.args
        ):
            return None

        path_arg = node.args[0].value
        exist_ok = False
        for kw in node.args:
            if kw.keyword and _is_name(kw.keyword, "exist_ok"):
                if isinstance(kw.value, cst.Name) and kw.value.value == "True":
                    exist_ok = True
                elif isinstance(kw.value, cst.Name) and kw.value.value == "False":
                    exist_ok = False
                break

        self.changes.append("os.makedirs() → Path().mkdir()")
        self.needs_pathlib_import = True

        mkdir_keywords = [
            cst.Arg(cst.Name("True"), keyword=cst.Name("parents")),
        ]
        if exist_ok:
            mkdir_keywords.append(cst.Arg(cst.Name("True"), keyword=cst.Name("exist_ok")))

        return cst.Call(
            func=cst.Attribute(
                value=cst.Call(
                    func=cst.Name("Path"),
                    args=(cst.Arg(path_arg),),
                ),
                attr=cst.Name("mkdir"),
            ),
            args=tuple(mkdir_keywords),
        )

    def _transform_path_join(self, node: cst.Call) -> cst.BaseExpression | None:
        if not (isinstance(node.func, cst.Attribute) and _is_os_path_call(node.func, name="join")):
            return None
        join_expr = _path_join_expression(node.args)
        if join_expr is None:
            return None
        self.changes.append("os.path.join() → Path / operator")
        self.needs_pathlib_import = True
        return join_expr

    def _transform_exists(self, node: cst.Call) -> cst.BaseExpression | None:
        if not (
            isinstance(node.func, cst.Attribute)
            and _is_os_path_call(node.func, name="exists")
            and node.args
        ):
            return None
        self.changes.append("os.path.exists() → Path().exists()")
        self.needs_pathlib_import = True
        return cst.Call(
            func=cst.Attribute(
                value=cst.Call(
                    func=cst.Name("Path"),
                    args=(cst.Arg(node.args[0].value),),
                ),
                attr=cst.Name("exists"),
            ),
        )

    def _transform_dirname(self, node: cst.Call) -> cst.BaseExpression | None:
        if not (
            isinstance(node.func, cst.Attribute)
            and _is_os_path_call(node.func, name="dirname")
            and node.args
        ):
            return None
        self.changes.append("os.path.dirname() → Path().parent")
        self.needs_pathlib_import = True
        return cst.Attribute(
            value=cst.Call(
                func=cst.Name("Path"),
                args=(cst.Arg(node.args[0].value),),
            ),
            attr=cst.Name("parent"),
        )

    def _transform_call(self, node: cst.Call) -> cst.BaseExpression | None:
        """Return rewritten call expression when a pathlib substitution exists.

        Parameters
        ----------
        node : cst.Call
            Call node to transform.

        Returns
        -------
        cst.BaseExpression | None
            Transformed expression | None if no transformation applies.
        """
        for transformer in (
            self._transform_makedirs,
            self._transform_path_join,
            self._transform_exists,
            self._transform_dirname,
        ):
            replacement = transformer(node)
            if replacement is not None:
                return replacement
        return None

    def _transform_with(self, original_node: cst.With, updated_node: cst.With) -> cst.With:
        """Rewrite ``with`` blocks wrapping ``open(os.path.join(...))`` patterns.

        Parameters
        ----------
        original_node : cst.With
            Original with statement node.
        updated_node : cst.With
            Updated with statement node.

        Returns
        -------
        cst.With
            Transformed with statement.
        """
        for index, (original_item, updated_item) in enumerate(
            zip(original_node.items, updated_node.items, strict=True)
        ):
            original_call = original_item.item
            if (
                not isinstance(original_call, cst.Call)
                or not isinstance(original_call.func, cst.Name)
                or original_call.func.value != "open"
                or not original_call.args
            ):
                continue

            first_arg = original_call.args[0]
            if first_arg.keyword is not None:
                continue

            join_call = first_arg.value
            if not (
                isinstance(join_call, cst.Call)
                and isinstance(join_call.func, cst.Attribute)
                and _is_os_path_call(join_call.func, name="join")
            ):
                continue

            path_expr = _path_join_expression(join_call.args)
            if path_expr is None:
                continue

            self.changes.append("open(os.path.join(...)) → Path(...).open()")
            self.needs_pathlib_import = True

            remaining_args: tuple[cst.Arg, ...] = ()
            if isinstance(updated_item.item, cst.Call):
                call_args = cast(
                    "tuple[cst.Arg, ...]",
                    tuple(updated_item.item.args),
                )
                remaining_args = call_args[1:]

            new_open_call = cst.Call(
                func=cst.Attribute(value=path_expr, attr=cst.Name("open")),
                args=remaining_args,
            )
            new_item = updated_item.with_changes(item=new_open_call)
            updated_items: list[cst.WithItem] = list(updated_node.items)
            updated_items[index] = new_item
            new_items_tuple: tuple[cst.WithItem, ...] = tuple(updated_items)
            return updated_node.with_changes(items=new_items_tuple)
        return updated_node


def _iter_simple_bodies(module: cst.Module) -> Sequence[cst.CSTNode]:
    items: list[cst.CSTNode] = []
    for statement in module.body:
        if isinstance(statement, cst.SimpleStatementLine):
            items.extend(statement.body)
    return items


def _module_has_pathlib(module: cst.Module) -> bool:
    for node in _iter_simple_bodies(module):
        imports_pathlib = isinstance(node, cst.Import) and any(
            isinstance(alias.name, cst.Name) and alias.name.value == "pathlib"
            for alias in node.names
        )
        from_pathlib = (
            isinstance(node, cst.ImportFrom)
            and isinstance(node.module, cst.Name)
            and node.module.value == "pathlib"
        )
        if imports_pathlib or from_pathlib:
            return True
    return False


def _insertion_index(module: cst.Module) -> int:
    index_after_future = 0
    for position, statement in enumerate(module.body):
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        if any(
            isinstance(item, cst.ImportFrom)
            and isinstance(item.module, cst.Name)
            and item.module.value == "__future__"
            for item in statement.body
        ):
            index_after_future = position + 1
    return index_after_future


def _pathlib_import_statement() -> cst.SimpleStatementLine:
    return cst.SimpleStatementLine(
        body=[
            cst.Import(
                names=[
                    cst.ImportAlias(
                        name=cst.Name("pathlib"),
                    ),
                ],
            ),
        ],
    )


def ensure_pathlib_import(
    module: cst.Module,
) -> cst.Module:
    """Add pathlib import if missing.

    Parameters
    ----------
    module : cst.Module
        Module node to modify.

    Returns
    -------
    cst.Module
        Module with pathlib import added if needed.
    """
    if _module_has_pathlib(module):
        return module

    new_body: list[cst.BaseStatement] = list(module.body)
    new_body.insert(_insertion_index(module), _pathlib_import_statement())
    new_body_tuple: tuple[cst.BaseStatement, ...] = tuple(new_body)
    return module.with_changes(body=new_body_tuple)


def transform_file(file_path: Path, *, dry_run: bool = False) -> list[str]:
    """Transform a single Python file.

    Parameters
    ----------
    file_path : Path
        Path to Python file to transform.
    dry_run : bool, optional
        If True, only report changes without modifying files.

    Returns
    -------
    list[str]
        List of change descriptions.
    """
    try:
        source_code = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.exception("Failed to read %s", file_path)
        return []

    try:
        module = cst.parse_module(source_code)
    except cst.ParserSyntaxError:
        logger.exception("Failed to parse %s", file_path)
        return []

    transformer = PathlibTransformer()
    transformed_module = module.visit(transformer)

    if transformer.needs_pathlib_import:
        transformed_module = ensure_pathlib_import(transformed_module)

    if transformer.changes:
        if not dry_run:
            try:
                file_path.write_text(
                    transformed_module.code,
                    encoding="utf-8",
                )
                logger.info("✓ Transformed %s", file_path)
            except OSError:
                logger.exception("Failed to write %s", file_path)
                return []
        else:
            logger.info("[DRY RUN] Would transform %s", file_path)

    return transformer.changes


def main() -> int:
    """Run codemod on target files or directories.

    Returns
    -------
    int
        Exit code (0 on success, 1 on error).
    """
    args = _parse_args()

    all_changes: dict[Path, list[str]] = {}
    target_paths: list[Path] = []

    for path in args.targets:
        if path.is_file() and path.suffix == ".py":
            target_paths.append(path)
        elif path.is_dir():
            target_paths.extend(path.rglob("*.py"))
        else:
            logger.warning("Skipping non-Python file: %s", path)

    if not target_paths:
        logger.error("No Python files found")
        return 1

    logger.info("Processing %d file(s)...", len(target_paths))

    for file_path in target_paths:
        changes = transform_file(file_path, dry_run=args.dry_run)
        if changes:
            all_changes[file_path] = changes

    if args.log is not None:
        log_path = args.log
        with log_path.open("w", encoding="utf-8") as f:
            f.write("Pathlib Codemod Change Log\n")
            f.write("=" * 50 + "\n\n")
            for file_path, changes in sorted(all_changes.items()):
                f.write(f"{file_path}\n")
                f.write("-" * len(str(file_path)) + "\n")
                for change in changes:
                    f.write(f"  {change}\n")
                f.write("\n")
        logger.info("Change log written to %s", log_path)

    total_changes = sum(len(changes) for changes in all_changes.values())
    logger.info("Total transformations: %d in %d file(s)", total_changes, len(all_changes))

    return 0


if __name__ == "__main__":
    sys.exit(main())
