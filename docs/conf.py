"""Agent-first Sphinx configuration.

- Static API docs via AutoAPI (no imports)
- Markdown via MyST
- Per-symbol "open in editor" links (linkcode + Griffe)
- Viewable source with line numbers (viewcode)
- JSON builder for machine-readable output

This file is robust to different repo shapes (``src/<pkg>`` or ``<pkg>`` at root) and
coordinates optional tooling dependencies with structured logging/problem details.  Failure
paths reference ``schema/examples/problem_details/search-missing-index.json`` to keep
observability consistent across the stack.
"""

from __future__ import annotations

import collections
import importlib
import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Protocol,
    cast,
    runtime_checkable,
)

import certifi
from docutils.parsers.rst import Directive
from sphinx.application import Sphinx
from sphinx_gallery.sorting import ExplicitOrder
from tools import ProblemDetailsParams, build_problem_details, get_logger
from tools.docs.gallery_manifest import (
    GalleryManifestError,
    explicit_order,
    load_gallery_manifest,
)
from tools.griffe_utils import resolve_griffe

from docs.types_facade import (
    AstroidBuilderProtocol,
    AstroidManagerProtocol,
    AutoapiParserProtocol,
    coerce_astroid_builder_factory,
    coerce_astroid_manager_factory,
    coerce_parser_class,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType

    from docutils import nodes

docs_shared = cast("Any", importlib.import_module("docs._scripts.shared"))

ENV = docs_shared.detect_environment()
docs_shared.ensure_sys_paths(ENV)
DOCS_SETTINGS = docs_shared.load_settings()

LOGGER = get_logger(__name__)
logging.getLogger(__name__).addHandler(logging.NullHandler())
LINKCODE_LOG = docs_shared.make_logger("docs_conf", artifact="linkcode", logger=LOGGER)


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    """Strongly typed project configuration derived from environment variables."""

    project_name: str
    author: str
    link_mode: str
    editor: str
    github_org: str
    github_repo: str
    github_sha: str | None


PROBLEM_DETAILS_SAMPLE: Final[dict[str, str | int]] = {
    "type": "https://kgfoundry.dev/docs/problems/link-resolution",
    "title": "Unable to resolve symbol location",
    "status": 500,
    "detail": "Griffe could not resolve the requested module or member.",
    "instance": "urn:kgfoundry:docs:linkcode:unresolved",
}


def _import_required_module(name: str) -> ModuleType:
    """Import ``name`` or raise a runtime error with context.

    Parameters
    ----------
    name : str
        Module name to import.

    Returns
    -------
    ModuleType
        Imported module.

    Raises
    ------
    RuntimeError
        If the module cannot be imported.
    """
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive guard
        problem = {
            **PROBLEM_DETAILS_SAMPLE,
            "detail": f"Required documentation dependency '{name}' is missing",
            "status": 500,
        }
        LOGGER.exception(
            "Documentation dependency missing",
            extra={
                "status": "dependency_missing",
                "module_name": name,
                "problem_details": problem,
            },
        )
        message = f"Required documentation dependency '{name}' is not installed"
        raise RuntimeError(message) from exc


def _require_attr(module: ModuleType, attr: str) -> object:
    """Return ``attr`` from ``module`` or raise a runtime error.

    Parameters
    ----------
    module : ModuleType
        Module to get attribute from.
    attr : str
        Attribute name to get.

    Returns
    -------
    object
        Attribute value.

    Raises
    ------
    RuntimeError
        If the attribute is missing.
    """
    try:
        return getattr(module, attr)
    except AttributeError as exc:  # pragma: no cover - defensive guard
        problem = {
            **PROBLEM_DETAILS_SAMPLE,
            "detail": f"Module '{module.__name__}' is missing attribute '{attr}'",
            "status": 500,
        }
        LOGGER.exception(
            "Documentation dependency attribute missing",
            extra={
                "status": "dependency_missing",
                "module_name": module.__name__,
                "attribute_name": attr,
                "problem_details": problem,
            },
        )
        message = f"Module '{module.__name__}' missing required attribute '{attr}'"
        raise RuntimeError(message) from exc


@runtime_checkable
class _AutoDocstringsModule(Protocol):
    MAGIC_METHOD_EXTENDED_SUMMARIES: Mapping[str, str]
    STANDARD_METHOD_EXTENDED_SUMMARIES: Mapping[str, str]
    PYDANTIC_ARTIFACT_SUMMARIES: Mapping[str, str]

    def summarize(self, name: str, kind: str) -> str:
        """Return a synthesized summary for the provided symbol."""
        ...


def get_project_settings(env: Mapping[str, str] | None = None) -> ProjectSettings:
    """Return strongly typed project settings derived from environment variables.

    Parameters
    ----------
    env : Mapping[str, str] | None, optional
        Environment variables mapping (defaults to os.environ).

    Returns
    -------
    ProjectSettings
        Typed project settings.
    """
    source = env if env is not None else os.environ
    project_name = source.get("PROJECT_NAME", "kgfoundry")
    author = source.get("PROJECT_AUTHOR", "kgfoundry Maintainers")
    link_mode = source.get("DOCS_LINK_MODE", "editor").lower()
    editor = source.get("DOCS_EDITOR", "vscode").lower()
    github_org = source.get("DOCS_GITHUB_ORG", "your-org")
    github_repo = source.get("DOCS_GITHUB_REPO", "your-repo")
    github_sha = source.get("DOCS_GITHUB_SHA")
    if link_mode not in {"editor", "github"}:
        LOGGER.warning(
            "Unsupported DOCS_LINK_MODE '%s', defaulting to 'editor'", link_mode
        )
        link_mode = "editor"
    if editor not in {"vscode", "pycharm"}:
        LOGGER.warning("Unsupported DOCS_EDITOR '%s', defaulting to 'vscode'", editor)
        editor = "vscode"
    return ProjectSettings(
        project_name=project_name,
        author=author,
        link_mode=link_mode,
        editor=editor,
        github_org=github_org,
        github_repo=github_repo,
        github_sha=github_sha,
    )


_BaseModel: type[object] | None
try:
    from pydantic import BaseModel as _PydanticBaseModel
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _BaseModel = None
else:
    _BaseModel = cast("type[object]", _PydanticBaseModel)

_auto_docstrings: ModuleType | None
try:
    from tools import auto_docstrings as _auto_docstrings
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _auto_docstrings = None

GriffeLoadingError: type[Exception] = RuntimeError
try:
    griffe_exceptions = importlib.import_module("griffe.exceptions")
except ModuleNotFoundError:  # pragma: no cover - griffe < 0.32
    pass
else:
    loading_error: object = getattr(griffe_exceptions, "LoadingError", RuntimeError)
    if isinstance(loading_error, type) and issubclass(loading_error, Exception):
        GriffeLoadingError = cast("type[Exception]", loading_error)

astroid_builder = _import_required_module("astroid.builder")
astroid_manager = _import_required_module("astroid.manager")
autoapi_parser = _import_required_module("autoapi._parser")
jsonimpl = _import_required_module("sphinxcontrib.serializinghtml.jsonimpl")
json_module = cast("ModuleType", _require_attr(jsonimpl, "json"))

astroid_manager_factory = coerce_astroid_manager_factory(astroid_manager)
astroid_builder_factory = coerce_astroid_builder_factory(astroid_builder)
AutoapiParserCls = coerce_parser_class(autoapi_parser)

AstroidManager = AstroidManagerProtocol
AstroidBuilder = AstroidBuilderProtocol
AutoapiParser = AutoapiParserProtocol


class GriffeNode(Protocol):
    """Subset of Griffe objects used for linkcode resolution."""

    filepath: Path | str | None
    lineno: int | None
    endlineno: int | None
    members: Mapping[str, GriffeNode] | None


class GriffeLoaderInstance(Protocol):
    """Minimal loader surface required for linkcode."""

    def load(self, module: str) -> GriffeNode:
        """Return the module graph for ``module``."""
        ...


class GriffeLoaderFactory(Protocol):
    """Callable factory returning Griffe loader instances."""

    def __call__(self, search_paths: Sequence[str]) -> GriffeLoaderInstance:
        """Return a loader configured with the provided search paths."""
        ...


# --- Project metadata (override via env if you like)
SETTINGS = get_project_settings()
project = SETTINGS.project_name
author = SETTINGS.author

# --- Paths
DOCS_DIR = Path(__file__).resolve().parent
ROOT = ENV.root
SRC_DIR = ENV.src
TOOLS_DIR = ENV.tools_dir


def _detect_pkg() -> str:
    """Return the primary package name, preferring ``src/`` packages.

    Returns
    -------
    str
        Primary package name.

    Raises
    ------
    RuntimeError
        If no Python package is found.
    """
    candidates: list[str] = []
    if SRC_DIR.exists():
        candidates += [p.parent.name for p in SRC_DIR.glob("*/__init__.py")]
    candidates += [
        p.parent.name for p in ROOT.glob("*/__init__.py") if p.parent.name != "docs"
    ]
    if not candidates:
        message = "No Python package found under src/ or project root"
        raise RuntimeError(message)
    # Prefer lowercase names if any; else first found
    lowers = [c for c in candidates if c.islower()]
    return lowers[0] if lowers else candidates[0]


PKG = os.environ.get("DOCS_PKG", _detect_pkg())

# Sphinx searches sys.path when rendering cross-refs; ensure paths are present.
for candidate in (SRC_DIR, ROOT, TOOLS_DIR):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

try:
    from tools.detect_pkg import detect_packages, detect_primary
except ImportError:  # pragma: no cover - fallback when tooling unavailable

    def detect_packages() -> list[str]:
        """Return empty package list when tooling is unavailable.

        Returns
        -------
        list[str]
            Empty list.
        """
        LOGGER.debug(
            "tools.detect_pkg.detect_packages unavailable; returning empty list"
        )
        return []

    def detect_primary() -> str:
        """Return fallback package name when tooling is unavailable.

        Returns
        -------
        str
            Fallback package name.
        """
        LOGGER.debug(
            "tools.detect_pkg.detect_primary unavailable; returning detected package"
        )
        return PKG


def _apply_auto_docstring_overrides() -> None:
    """Inject extended summaries for Pydantic helpers and magic methods."""
    if _BaseModel is None or _auto_docstrings is None:
        return

    auto_docstrings = cast("_AutoDocstringsModule", _auto_docstrings)

    overrides: dict[str, str] = {}
    overrides.update(auto_docstrings.MAGIC_METHOD_EXTENDED_SUMMARIES)
    overrides.update(auto_docstrings.STANDARD_METHOD_EXTENDED_SUMMARIES)
    overrides.update(auto_docstrings.PYDANTIC_ARTIFACT_SUMMARIES)

    for name, extended in overrides.items():
        attr: object | None = getattr(_BaseModel, name, None)
        if attr is None:
            continue
        summary = auto_docstrings.summarize(name, "function")
        doc_text = f"{summary}\n\n{extended}"
        with suppress(
            AttributeError, TypeError
        ):  # pragma: no cover - descriptor without doc support
            attr.__doc__ = doc_text


_AUTOAPI_DOC_OVERRIDES: dict[str, str] = {}


def _build_autoapi_doc_overrides() -> None:
    """Prepare docstring overrides for members missing extended summaries."""
    if _AUTOAPI_DOC_OVERRIDES:
        return

    if _auto_docstrings is None:
        return

    auto_docstrings = cast("_AutoDocstringsModule", _auto_docstrings)

    overrides: dict[str, str] = {}
    overrides.update(auto_docstrings.MAGIC_METHOD_EXTENDED_SUMMARIES)
    overrides.update(auto_docstrings.STANDARD_METHOD_EXTENDED_SUMMARIES)
    overrides.update(auto_docstrings.PYDANTIC_ARTIFACT_SUMMARIES)

    for name, extended in overrides.items():
        summary = auto_docstrings.summarize(name, "function")
        _AUTOAPI_DOC_OVERRIDES[name] = f"{summary}\n\n{extended}"


def _autoapi_skip_member(*event: object) -> bool | None:
    """Skip inherited helpers that rely on autogenerated Pydantic internals.

    Parameters
    ----------
    *event : object
        AutoAPI event arguments.

    Returns
    -------
    bool | None
        True to skip member, False to include, None to use default.
    """
    if len(event) != AUTOAPI_EVENT_ARG_COUNT:
        return None
    _, _, name, obj, _, _ = cast("AutoapiEvent", event)
    if not isinstance(name, str):
        return None

    _build_autoapi_doc_overrides()

    simple = name.split(".")[-1]
    doc_override = _AUTOAPI_DOC_OVERRIDES.get(simple)
    if doc_override and hasattr(obj, DOCSTRING_ATTR):
        setattr(obj, DOCSTRING_ATTR, doc_override)
    return None


_PACKAGES: list[str] = []
if os.environ.get("DOCS_PKG"):
    _PACKAGES = [
        pkg.strip() for pkg in os.environ["DOCS_PKG"].split(",") if pkg.strip()
    ]
if not _PACKAGES:
    _PACKAGES = detect_packages()
if not _PACKAGES:
    _PACKAGES = [detect_primary()]

_apply_auto_docstring_overrides()
_build_autoapi_doc_overrides()

numpydoc_validation_exclude = sorted(
    {rf"^{re.escape(name)}$" for name in _AUTOAPI_DOC_OVERRIDES}
)

AutoapiEvent = tuple[Sphinx, str, str, object, bool, Mapping[str, object]]
AUTOAPI_EVENT_ARG_COUNT = 6
DOCSTRING_ATTR = "docstring"

extensions = [
    "myst_parser",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx.ext.linkcode",
    "sphinx.ext.graphviz",
    "sphinx.ext.inheritance_diagram",
    "autoapi.extension",  # static API docs (no import)
    "sphinxcontrib.mermaid",
    "numpydoc",
    "numpydoc_validation",
    "sphinx_gallery.gen_gallery",
]

napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_use_param = True
napoleon_use_rtype = False

# Treat missing references as hard failures so documentation stays healthy.
nitpicky = True

# Enforce strict NumPy validation across the codebase.
numpydoc_validation_checks = {
    "GL01",
    "SS01",
    "ES01",
    "RT01",
    "PR01",
}
numpydoc_xref_param_type = True
numpydoc_xref_ignore = {"default", "optional"}
numpydoc_xref_aliases = {
    # Internal models and aliases (TypeAlias entries resolve as ``py:data``).
    "Concept": ("py:class", "src.ontology.catalog.Concept"),
    "FloatArray": ("py:data", "src.vectorstore_faiss.gpu.FloatArray"),
    "Id": ("py:data", "src.kgfoundry_common.models.Id"),
    "NavMap": ("py:class", "src.kgfoundry_common.navmap_types.NavMap"),
    "Stability": ("py:data", "src.kgfoundry_common.navmap_types.Stability"),
    "StrArray": ("py:data", "src.vectorstore_faiss.gpu.StrArray"),
    "VecArray": ("py:data", "src.search_api.faiss_adapter.VecArray"),
    "SupportsHttp": ("py:class", "src.search_client.client.SupportsHttp"),
    "SupportsResponse": ("py:class", "src.search_client.client.SupportsResponse"),
    # Third-party helpers that numpydoc otherwise classifies incorrectly.
    "NDArray": ("py:data", "numpy.typing.NDArray"),
    "numpy.typing.NDArray": ("py:data", "numpy.typing.NDArray"),
    "pyarrow.schema": ("py:function", "pyarrow.schema"),
    "HTTPException": ("py:class", "fastapi.HTTPException"),
    "Depends": ("py:function", "fastapi.Depends"),
    "Header": ("py:function", "fastapi.Header"),
    "typer.Argument": ("py:class", "typer.Argument"),
    "typer.Option": ("py:class", "typer.Option"),
    "typer.Exit": ("py:exc", "typer.Exit"),
}

# Use whatever theme you prefer; pydata_sphinx_theme is widely used.
html_theme = os.environ.get("SPHINX_THEME", "pydata_sphinx_theme")

# MyST (Markdown) features
myst_enable_extensions = ["colon_fence", "deflist", "linkify"]
# Generate id attributes for headings up to h3 so intra-page links stay stable.
myst_heading_anchors = 3

# Use the certifi CA bundle so intersphinx requests succeed in restricted environments.
tls_cacert = certifi.where()
# Fall back to skipping certificate verification when the bundled store is insufficient (e.g. CI sandboxes).
tls_verify = False

# AutoAPI: scan each detected package directory so module names match import paths
autoapi_type = "python"
_AUTOAPI_DIRS: list[str] = []
for _pkg in _PACKAGES:
    _candidate = SRC_DIR / _pkg.replace(".", "/")
    if _candidate.exists():
        _AUTOAPI_DIRS.append(str(_candidate))
if not _AUTOAPI_DIRS:
    _AUTOAPI_DIRS = [str(SRC_DIR if SRC_DIR.exists() else ROOT)]
autoapi_dirs = _AUTOAPI_DIRS
autoapi_root = "autoapi"
autoapi_output_dir = "autoapi"
autoapi_add_toctree_entry = True
autoapi_python_module_prefix = "src."
autoapi_generate_module_toc = True
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "special-members",
    "imported-members",
    "private-members",
]
# Include package __init__ modules so AutoAPI emits package-level toctrees.
autoapi_ignore: list[str] = [
    "tools/navmap/check_navmap.py",
    # Exclude deprecated exception aliases to avoid duplicate documentation targets.
    "*/kgfoundry_common/exceptions.py",
]


def _build_autoapi_parser(
    base: type[AutoapiParserProtocol],
) -> type[AutoapiParserProtocol]:
    """Return AutoAPI parser subclass with namespace-aware file parsing.

    Parameters
    ----------
    base : type[AutoapiParserProtocol]
        Base parser class to subclass.

    Returns
    -------
    type[AutoapiParserProtocol]
        Parser subclass with namespace-aware parsing.
    """

    class KgAutoapiParser(base):
        """Parser that resolves module namespaces without mutating private APIs."""

        def _parse_file(  # pragma: no cover - compatibility shim
            self,
            file_path: str,
            condition: Callable[[str], bool],
        ) -> object:
            path = Path(file_path)
            module_parts: collections.deque[str] = collections.deque()
            if path.name not in {"__init__.py", "__init__.pyi"}:
                module_parts.append(path.stem)
            parent = path.parent
            while str(parent) and condition(str(parent)):
                module_parts.appendleft(parent.name)
                parent = parent.parent

            module_name = ".".join(module_parts)
            manager = astroid_manager_factory()
            builder = astroid_builder_factory(manager)
            node = builder.file_build(file_path, module_name)
            return self.parse(node)

    return cast("type[AutoapiParserProtocol]", KgAutoapiParser)


KgAutoapiParser = _build_autoapi_parser(AutoapiParserCls)


cast("Any", autoapi_parser).Parser = KgAutoapiParser
AutoapiParserCls = KgAutoapiParser

# Show type hints nicely
autodoc_typehints = "description"

# Cross-link to Python stdlib docs
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "pyarrow": ("https://arrow.apache.org/docs/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
    "fastapi": ("https://fastapi.tiangolo.com/", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
    # Scientific computing stack used throughout vector operations.
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    # HTTP and testing stacks referenced in API docs.
    "httpx": (
        "https://httpx.readthedocs.io/en/stable/",
        "https://httpx.readthedocs.io/en/stable/objects.inv",
    ),
    "pytest": ("https://docs.pytest.org/en/stable/", None),
    # Best-effort mappings for CLI/database integrations.
    "typer": ("https://typer.tiangolo.com/", None),
    "duckdb": ("https://duckdb.org/docs/api/python/", None),
}

# Fallback external links for types missing from upstream inventories.
extlinks = {
    "numpy-type": ("https://numpy.org/doc/stable/reference/generated/%s.html", "%s"),
    "pyarrow-type": ("https://arrow.apache.org/docs/python/generated/%s.html", "%s"),
}

# Show line numbers in rendered source pages (Sphinx >= 7.2)
viewcode_line_numbers = True

suppress_warnings = ["myst.header", "misc.restructuredtext"]

EXAMPLES_DIR = (DOCS_DIR.parent / "examples").resolve()
GALLERY_MANIFEST_PATH = DOCS_DIR / "gallery" / "manifest.json"
_GALLERY_MANIFEST_ERROR = "Unable to load gallery manifest"

try:
    GALLERY_MANIFEST = load_gallery_manifest(GALLERY_MANIFEST_PATH)
except GalleryManifestError as exc:  # pragma: no cover - validated in CI builds
    LOGGER.exception(
        "Failed to load gallery manifest",
        extra={
            "status": "gallery_manifest_error",
            "manifest_path": str(GALLERY_MANIFEST_PATH),
        },
    )
    raise RuntimeError(_GALLERY_MANIFEST_ERROR) from exc

GALLERY_EXAMPLE_FILENAMES = explicit_order(GALLERY_MANIFEST)

sphinx_gallery_conf = {
    "examples_dirs": str(EXAMPLES_DIR),
    "gallery_dirs": "gallery",
    "filename_pattern": r".*\.py",
    "within_subsection_order": ExplicitOrder(GALLERY_EXAMPLE_FILENAMES),
    "download_all_examples": True,
    "remove_config_comments": True,
    "doc_module": tuple(_PACKAGES),
    "run_stale_examples": False,
    "plot_gallery": False,
    "backreferences_dir": "gen_modules/backrefs",
    "first_notebook_cell": None,  # Do not prepend setup cells to rendered notebooks.
    "line_numbers": False,  # Produce cleaner code blocks in gallery pages.
    "reference_url": {  # Keep cross-reference targets local to this project.
        "sphinx_gallery": None,
    },
    "capture_repr": (),  # Avoid capturing repr output unless explicitly requested.
    "expected_failing_examples": [],  # Fail the build if an example regresses unexpectedly.
    "min_reported_time": 0,  # Always surface execution timing metadata in reports.
}

# Ensure JSON builder can serialize lru_cache wrappers


class DocsJSONEncoder(json.JSONEncoder):
    """JSON encoder that can serialize ``functools.lru_cache`` wrappers."""

    def default(
        self, o: object
    ) -> object:  # pragma: no cover - exercised in Sphinx build
        """Return a JSON-safe representation for cache wrappers and delegates to super.

        Parameters
        ----------
        o : object
            Object to serialize.

        Returns
        -------
        object
            JSON-safe representation or result from super().default().
        """
        if o.__class__.__name__ == "_lru_cache_wrapper":
            return repr(o)
        return super().default(o)


# Override JSONEncoder default to render lru_cache wrappers
cast("Any", json_module).JSONEncoder = DocsJSONEncoder
cast("Any", json).JSONEncoder = DocsJSONEncoder

# --- Build deep links per symbol without importing your code (use Griffe)
griffe_api = resolve_griffe()
loader_factory = cast("GriffeLoaderFactory", griffe_api.loader_type)
_loader = loader_factory(search_paths=[str(SRC_DIR if SRC_DIR.exists() else ROOT)])
_MODULE_CACHE: dict[str, GriffeNode | None] = {}
PKG = _PACKAGES[0]

# Ensure sphinx-gallery backref directory exists to avoid missing-path errors
(DOCS_DIR / "gen_modules" / "backrefs").mkdir(parents=True, exist_ok=True)


def _get_root(module: str | None) -> GriffeNode | None:
    top = module.split(".", 1)[0] if module else PKG
    if top not in _MODULE_CACHE:
        try:
            _MODULE_CACHE[top] = _loader.load(top)
        except (
            GriffeLoadingError,
            ModuleNotFoundError,
            FileNotFoundError,
            OSError,
        ) as exc:
            problem_details = build_problem_details(
                ProblemDetailsParams(
                    type="https://kgfoundry.dev/problems/docs-linkcode-loader",
                    title="Failed to load module for linkcode lookup",
                    status=500,
                    detail=f"Griffe failed to load module '{top}': {exc}",
                    instance=f"urn:docs:linkcode:loader:{top}",
                    extensions={"module": top},
                )
            )
            LINKCODE_LOG.warning(
                "Failed to load module for linkcode lookup",
                extra={
                    "problem_details": problem_details,
                    "status": "loader_error",
                    "module_name": top,
                },
            )
            _MODULE_CACHE[top] = None
    return _MODULE_CACHE[top]


def _child_member(node: GriffeNode, name: str) -> GriffeNode | None:
    """Return the member named ``name`` from ``node`` when present.

    Parameters
    ----------
    node : GriffeNode
        Node to get member from.
    name : str
        Member name to look up.

    Returns
    -------
    GriffeNode | None
        Member node if found, None otherwise.
    """
    members: object | None = getattr(node, "members", None)
    if isinstance(members, Mapping):
        child = members.get(name)
        if child is not None:
            return cast("GriffeNode", child)
    return None


def _resolve_members(root: GriffeNode, parts: Sequence[str]) -> GriffeNode | None:
    """Traverse ``parts`` from ``root`` returning the final node when present.

    Parameters
    ----------
    root : GriffeNode
        Root node to start traversal from.
    parts : Sequence[str]
        Sequence of member names to traverse.

    Returns
    -------
    GriffeNode | None
        Final node if all parts resolve, None otherwise.
    """
    current = root
    for part in parts:
        if not part:
            continue
        next_node = _child_member(current, part)
        if next_node is None:
            return None
        current = next_node
    return current


def _lookup(module: str | None, fullname: str | None) -> tuple[str, int, int] | None:
    """Return ``(abs_path, start, end)`` for the requested symbol.

    Parameters
    ----------
    module : str | None
        Module name to look up in.
    fullname : str | None
        Fully qualified symbol name.

    Returns
    -------
    tuple[str, int, int] | None
        Tuple of (absolute path, start line, end line) if found, None otherwise.
    """
    root = _get_root(module)
    if root is None:
        return None

    target = root
    if module:
        module_parts = module.split(".")
        target_module = _resolve_members(root, module_parts[1:])
        if target_module is None:
            return None
        target = target_module

    full_parts = (fullname or "").split(".")
    resolved = _resolve_members(target, full_parts)
    if resolved is None:
        return None

    file_rel_obj = getattr(resolved, "relative_package_filepath", None)
    if isinstance(file_rel_obj, Path):
        file_rel_str = file_rel_obj.as_posix()
    elif isinstance(file_rel_obj, str):
        file_rel_str = file_rel_obj
    else:
        return None

    start_obj = getattr(resolved, "lineno", None)
    if not isinstance(start_obj, int):
        return None

    end_obj = getattr(resolved, "endlineno", None)
    end_int = end_obj if isinstance(end_obj, int) else start_obj

    base = SRC_DIR if SRC_DIR.exists() else ROOT
    abs_path = base / file_rel_str
    return str(abs_path.resolve()), start_obj, end_int


# Link modes:
#   DOCS_LINK_MODE=editor (default): vscode://file/<abs>:line:col
#   DOCS_LINK_MODE=github: https://github.com/<org>/<repo>/blob/<sha>/<rel>#Lstart-Lend
LINK_MODE = DOCS_SETTINGS.link_mode
EDITOR = SETTINGS.editor


def _github_url(relpath: str, start: int, end: int | None) -> str:
    org = DOCS_SETTINGS.github_org or SETTINGS.github_org
    repo = DOCS_SETTINGS.github_repo or SETTINGS.github_repo
    if not org or not repo:
        return ""
    sha = docs_shared.resolve_git_sha(ENV, DOCS_SETTINGS, logger=LINKCODE_LOG)
    rng = f"#L{start}-L{end}" if end and end >= start else f"#L{start}"
    return f"https://github.com/{org}/{repo}/blob/{sha}/{relpath}{rng}"


def linkcode_resolve(domain: str, info: Mapping[str, str | None]) -> str | None:
    """Resolve Sphinx linkcode directives to editor or GitHub URLs.

    Parameters
    ----------
    domain : str
        Sphinx domain (e.g., 'py').
    info : Mapping[str, str | None]
        Symbol information mapping.

    Returns
    -------
    str | None
        Resolved URL if successful, None otherwise.
    """
    module_name = info.get("module")
    if domain != "py" or not module_name:
        return None
    fullname = info.get("fullname", "")
    res = _lookup(module_name, fullname)
    if not res:
        problem_details = build_problem_details(
            ProblemDetailsParams(
                type="https://kgfoundry.dev/problems/docs-linkcode-resolution",
                title="Unable to resolve symbol location",
                status=404,
                detail=f"Unable to resolve {module_name}.{fullname}",
                instance=f"urn:docs:linkcode:missing:{module_name}.{fullname}",
                extensions={"module": module_name, "fullname": fullname},
            )
        )
        LINKCODE_LOG.debug(
            "linkcode resolution failed",
            extra={
                "problem_details": problem_details,
                "status": "linkcode_missing",
            },
        )
        return None
    abs_path, start, end = res
    if LINK_MODE == "github":
        rel = os.path.relpath(abs_path, ROOT)
        url = _github_url(rel, start, end)
        return url or None
    if EDITOR == "vscode":
        return f"vscode://file/{abs_path}:{start}:1"
    if EDITOR == "pycharm":
        return f"pycharm://open?file={abs_path}&line={start}"
    return None


nitpick_ignore = {
    # NumPy scalar aliases do not expose inventory targets.
    ("py:class", "numpy.float32"),
    ("py:class", "np.float32"),
    ("py:class", "np.int64"),
    ("py:class", "np.str_"),
    ("py:class", "NDArray"),
    ("py:class", "numpy.typing.NDArray"),
    ("py:class", "pyarrow.schema"),
    ("py:class", "Id"),
    ("py:class", "src.kgfoundry_common.models.Id"),
    ("py:class", "Stability"),
    ("py:class", "src.kgfoundry_common.navmap_types.Stability"),
    ("py:class", "VecArray"),
    ("py:class", "src.search_api.faiss_adapter.VecArray"),
    ("py:class", "FloatArray"),
    ("py:class", "StrArray"),
    ("py:class", "src.vectorstore_faiss.gpu.FloatArray"),
    ("py:class", "src.vectorstore_faiss.gpu.StrArray"),
    ("py:class", "SupportsHttp"),
    ("py:class", "src.search_client.client.SupportsHttp"),
    ("py:exc", "HTTPException"),
    ("py:class", "Concept"),
    ("py:class", "src.ontology.catalog.Concept"),
    # Third-party projects without accessible inventories.
    ("py:class", "duckdb.DuckDBPyConnection"),
    ("py:class", "typer.Argument"),
    ("py:class", "typer.Option"),
    ("py:exc", "typer.Exit"),
}

nitpick_ignore_regex: list[tuple[str, str]] = []


class GalleryTagsDirective(Directive):
    """Lightweight directive so ``..

    tags::`` blocks parse without warnings.
    """

    has_content = True

    def run(self) -> list[nodes.Node]:
        """Return an empty node list so Sphinx accepts ``..

        tags::`` blocks.

        Returns
        -------
        list[nodes.Node]
            Empty list.
        """
        if self.content:
            LOGGER.debug(
                "tags directive content ignored", extra={"tags": list(self.content)}
            )
        return []


def setup(app: Sphinx) -> None:  # pragma: no cover - Sphinx integration hook
    """Register custom directives when Sphinx loads the config module."""
    app.add_directive("tags", GalleryTagsDirective)
    app.connect("autoapi-skip-member", _autoapi_skip_member)
