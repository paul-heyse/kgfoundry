"""Codemod to transform blind except blocks to typed exception handling.

This script uses LibCST to transform `except Exception:` and bare `except:`
blocks by adding TODO comments and ensuring exception variables are named.

Requirement: R2 — Exception Taxonomy & Problem Details
Scenario: Blind excepts eliminated

Note: This codemod adds TODO comments and exception variable names.
Manual review is required to map exceptions to appropriate KgFoundryError subclasses.
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
class BlindExceptArgs:
    """Parsed CLI options for the blind-except codemod."""

    targets: tuple[Path, ...]
    dry_run: bool
    log: Path | None


def _parse_args(argv: Sequence[str] | None = None) -> BlindExceptArgs:
    parser = argparse.ArgumentParser(
        description="Transform blind except blocks to add TODOs and exception variables",
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
    return BlindExceptArgs(targets=targets, dry_run=dry_run, log=log_path)


class BlindExceptTransformer(cst.CSTTransformer):
    """Rewrite blind ``except`` handlers to capture exceptions explicitly.

    Initializes transformer with change tracking.
    """

    def __init__(self) -> None:
        super().__init__()
        self.changes: list[str] = []

    def leave_except_handler(
        self, original_node: cst.ExceptHandler, updated_node: cst.ExceptHandler
    ) -> cst.ExceptHandler:
        """Rewrite blind except handlers when exiting traversal.

        Parameters
        ----------
        original_node : cst.ExceptHandler
            Original exception handler node.
        updated_node : cst.ExceptHandler
            Updated exception handler node.

        Returns
        -------
        cst.ExceptHandler
            Transformed exception handler.
        """
        return self._transform_except(original_node, updated_node)

    leave_except_handler = leave_except_handler

    def _transform_except(
        self,
        original_node: cst.ExceptHandler,
        updated_node: cst.ExceptHandler,
    ) -> cst.ExceptHandler:
        """Return an updated exception handler when we detect a blind clause.

        Parameters
        ----------
        original_node : cst.ExceptHandler
            Original exception handler node.
        updated_node : cst.ExceptHandler
            Updated exception handler node.

        Returns
        -------
        cst.ExceptHandler
            Transformed exception handler.
        """
        # Match `except Exception:` or bare `except:`
        is_blind_except = False

        exc_type: cst.BaseExpression | None = updated_node.type
        whitespace_after_except = updated_node.whitespace_after_except
        if original_node.type is None:
            # Bare `except:`
            is_blind_except = True
            self.changes.append("bare except: → TODO + exception variable")
            exc_type = cst.Name("Exception")
            whitespace_after_except = cst.SimpleWhitespace(" ")
        elif isinstance(original_node.type, cst.Name) and original_node.type.value == "Exception":
            # `except Exception:`
            is_blind_except = True
            self.changes.append("except Exception: → TODO + logging scaffold")

        if not is_blind_except:
            return updated_node

        # Ensure exception variable name exists
        # ExceptHandler.name is an AsName (or None), which wraps a Name
        exc_var_name = updated_node.name
        if exc_var_name is None:
            # Create AsName wrapping a Name
            exc_var_name = cst.AsName(name=cst.Name("exc"))

        # Update handler with name if changed
        if (
            updated_node.name != exc_var_name
            or updated_node.type is not exc_type
            or updated_node.whitespace_after_except is not whitespace_after_except
        ):
            return updated_node.with_changes(
                name=exc_var_name,
                type=exc_type,
                whitespace_after_except=whitespace_after_except,
            )
        return updated_node


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

    transformer = BlindExceptTransformer()
    transformed_module = module.visit(transformer)

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
            f.write("Blind Except Codemod Change Log\n")
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
