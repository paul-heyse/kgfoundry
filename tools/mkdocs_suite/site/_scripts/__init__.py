"""MkDocs suite build-time scripts."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from yaml.nodes import Node, ScalarNode

__all__ = ["__doc__", "load_repo_settings"]


EDIT_URI_BRANCH_INDEX = 1
DEFAULT_BRANCH_FALLBACK = "main"
_SUITE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SUITE_ROOT.parents[1]
_SRC_ROOT = _REPO_ROOT / "src"

for candidate in (str(_REPO_ROOT), str(_SRC_ROOT)):
    while candidate in sys.path:
        sys.path.remove(candidate)
    sys.path.insert(0, candidate)
_DEFAULT_MKDOCS_PATH = _SUITE_ROOT / "mkdocs.yml"


def _construct_python_name(
    loader: yaml.SafeLoader, _suffix: str, node: Node
) -> str | None:
    """Return the raw value for ``!!python/name`` tags used by MkDocs plugins.

    ``mkdocs.yml`` relies on ``!!python/name:...`` tags for plugin wiring. The
    default :class:`yaml.SafeLoader` refuses to process those tags, which would
    otherwise cause ``yaml.safe_load`` to raise ``ConstructorError``. By
    registering a multi-constructor we fall back to the scalar value while
    keeping the loader ``safe``.

    Parameters
    ----------
    loader : yaml.SafeLoader
        YAML loader instance processing the node.
    _suffix : str
        Tag suffix (unused, kept for constructor signature compatibility).
    node : Node
        YAML node containing the scalar value.

    Returns
    -------
    str | None
        The scalar value extracted from the node, or ``None`` if the node
        cannot be constructed as a scalar.
    """
    if not isinstance(node, ScalarNode):
        return None
    return loader.construct_scalar(node)


# ``yaml.safe_load`` internally relies on :class:`yaml.SafeLoader`. Register a
# permissive constructor ahead of time so loading the MkDocs config succeeds
# even when optional plugins inject ``!!python/name`` tags.
yaml.SafeLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:", _construct_python_name
)


def _coerce_repo_url(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def load_repo_settings(
    mkdocs_config_path: Path | str | None = None,
) -> tuple[str | None, str | None]:
    """Return the repository URL and default branch from ``mkdocs.yml``.

    Parameters
    ----------
    mkdocs_config_path : Path | str | None
        Optional override for the MkDocs configuration path. When omitted the
        helper uses the canonical ``tools/mkdocs_suite/mkdocs.yml`` location.

    Returns
    -------
    tuple[str | None, str | None]
        ``(repo_url, branch)`` pair where missing values are surfaced as
        ``None``. The branch defaults to ``"main"`` when the MkDocs
        configuration omits a resolvable ``edit_uri``.
    """
    path = (
        Path(mkdocs_config_path)
        if mkdocs_config_path is not None
        else _DEFAULT_MKDOCS_PATH
    )
    if not path.exists():
        return None, None

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError:  # pragma: no cover - defensive guard
        return None, None
    except yaml.YAMLError:  # pragma: no cover - defensive guard
        return None, DEFAULT_BRANCH_FALLBACK

    config = payload if isinstance(payload, dict) else {}

    repo_url = _coerce_repo_url(config.get("repo_url"))
    edit_uri = config.get("edit_uri")

    branch: str | None = None
    if isinstance(edit_uri, str):
        parts = edit_uri.strip("/").split("/")
        if parts and parts[0] == "edit" and len(parts) > EDIT_URI_BRANCH_INDEX:
            candidate = parts[EDIT_URI_BRANCH_INDEX].strip()
            if candidate:
                branch = candidate

    if not branch:
        branch = DEFAULT_BRANCH_FALLBACK

    return repo_url, branch
