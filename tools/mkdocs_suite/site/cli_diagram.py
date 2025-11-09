"""Public helpers for generating CLI diagrams used in documentation tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from tools.mkdocs_suite.docs._scripts import gen_cli_diagram as _impl

OperationEntry = _impl.OperationEntry

__all__ = ["OperationEntry", "collect_operations", "write_diagram"]

if TYPE_CHECKING:  # pragma: no cover - typing aid
    from tools._shared.cli_tooling import CLIToolingContext


def collect_operations(
    *,
    context: CLIToolingContext | None = None,
    interface_id: str | None = None,
    click_cmd: object | None = None,
) -> list[OperationEntry]:
    """Return CLI operations derived from the shared CLI tooling context.

    Parameters
    ----------
    context : CLIToolingContext | None, optional
        Optional pre-loaded tooling context to reuse across calls.
    interface_id : str | None, optional
        Override for the CLI interface identifier. Defaults to the repository
        standard when ``None``.
    click_cmd : object | None, optional
        Pre-resolved click command tree used for traversal.

    Returns
    -------
    list[OperationEntry]
        Materialised list of CLI operation metadata tuples.
    """
    return _impl.collect_operations(
        context, interface_id=interface_id, click_cmd=click_cmd
    )


def write_diagram(operations: Sequence[OperationEntry]) -> None:
    """Write the CLI diagram to the MkDocs virtual filesystem."""
    _impl.write_diagram(operations)
