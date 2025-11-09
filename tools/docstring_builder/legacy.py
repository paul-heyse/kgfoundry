"""Legacy auto-docstring helpers backed by the docstring-builder pipelines."""

from __future__ import annotations

import ast
import contextvars
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from tools.docstring_builder.apply import apply_edits
from tools.docstring_builder.config import DEFAULT_MARKER
from tools.docstring_builder.harvest import HarvestResult
from tools.docstring_builder.models import DocstringIRParameter
from tools.docstring_builder.overrides import (
    _STANDARD_METHOD_EXTENDED_SUMMARIES,
    DEFAULT_MAGIC_METHOD_FALLBACK,
    DEFAULT_PYDANTIC_ARTIFACT_SUMMARY,
    MAGIC_METHOD_EXTENDED_SUMMARIES,
    PYDANTIC_ARTIFACT_SUMMARIES,
    QUALIFIED_NAME_OVERRIDES,
)
from tools.docstring_builder.overrides import (
    _is_magic as overrides_is_magic,
)
from tools.docstring_builder.overrides import (
    _is_pydantic_artifact as overrides_is_pydantic_artifact,
)
from tools.docstring_builder.overrides import (
    extended_summary as overrides_extended_summary,
)
from tools.docstring_builder.overrides import (
    summarize as overrides_summarize,
)
from tools.docstring_builder.schema import DocstringEdit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tools.docstring_builder.models import ParameterKind

# Context variables for thread-safe repository metadata access
_repo_root_ctx: contextvars.ContextVar[Path] = contextvars.ContextVar(
    "_repo_root_ctx", default=Path(__file__).resolve().parents[2]
)
_src_root_ctx: contextvars.ContextVar[Path] = contextvars.ContextVar(
    "_src_root_ctx", default=Path(__file__).resolve().parents[2] / "src"
)


class LegacyConfig:
    """Thread-safe singleton for repository metadata configuration.

    Uses contextvars for thread-safe access, allowing per-context overrides while maintaining a
    default value. This replaces mutable global variables with a structured, testable configuration
    mechanism.
    """

    _instance: LegacyConfig | None = None

    def __new__(cls) -> Self:
        """Return singleton instance."""
        if cls._instance is None:
            cls._instance = cast("LegacyConfig", super().__new__(cls))
        return cast("Self", cls._instance)

    @property
    def repo_root(self) -> Path:
        """Get the repository root path for the current context."""
        return _repo_root_ctx.get()

    @property
    def src_root(self) -> Path:
        """Get the source root path for the current context."""
        return _src_root_ctx.get()

    @classmethod
    def configure(cls, repo_root: Path, src_root: Path) -> None:
        """Configure repository roots for the current context.

        Parameters
        ----------
        repo_root : Path
            Repository root directory.
        src_root : Path
            Source root directory.
        """
        _repo_root_ctx.set(repo_root)
        _src_root_ctx.set(src_root)


def configure_roots(repo_root: Path, src_root: Path) -> None:
    """Override the repository and source roots used by legacy helpers.

    This function maintains backward compatibility with existing code
    while delegating to the thread-safe LegacyConfig singleton.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.
    src_root : Path
        Source root directory.
    """
    LegacyConfig.configure(repo_root, src_root)


# Public API: Module-level constants for backward compatibility
# These delegate to the thread-safe config singleton
def _get_repo_root() -> Path:
    """Get repository root from thread-safe config.

    Returns
    -------
    Path
        Repository root directory path.
    """
    return LegacyConfig().repo_root


def _get_src_root() -> Path:
    """Get source root from thread-safe config.

    Returns
    -------
    Path
        Source root directory path.
    """
    return LegacyConfig().src_root


# Module-level accessors that maintain backward compatibility
# These are computed on each access to support context-local overrides
REPO_ROOT: Path = _get_repo_root()
SRC_ROOT: Path = _get_src_root()


STANDARD_METHOD_EXTENDED_SUMMARIES = _STANDARD_METHOD_EXTENDED_SUMMARIES


@dataclass(slots=True, frozen=True)
class _CollectedSymbol:
    qname: str
    node: ast.AST
    kind: str
    docstring: str | None


@dataclass(slots=True, frozen=True)
class _RequiredSectionsContext:
    """Contextual data required to enforce docstring section completeness."""

    kind: str
    parameters: Sequence[DocstringIRParameter]
    returns_annotation: str | None
    raises: Sequence[str]
    is_public: bool


@dataclass(slots=True, frozen=True)
class _ExampleContext:
    module_name: str
    name: str
    parameters: Sequence[DocstringIRParameter]
    include_import: bool
    is_async: bool = False
    returns_value: bool = True


class _SymbolCollector(ast.NodeVisitor):
    """Collect callable and class symbols for docstring generation.

    Parameters
    ----------
    module_name : str
        Module qualified name.
    """

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self.namespace: list[str] = []
        self.symbols: list[_CollectedSymbol] = []

    def _qualify(self, name: str) -> str:
        return ".".join(part for part in [self.module_name, *self.namespace, name] if part)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definition and collect symbol.

        Parameters
        ----------
        node : ast.ClassDef
            ClassDef AST node.
        """
        qname = self._qualify(node.name)
        docstring = ast.get_docstring(node, clean=False)
        self.symbols.append(_CollectedSymbol(qname, node, "class", docstring))
        self.namespace.append(node.name)
        self.generic_visit(node)
        self.namespace.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition and collect symbol.

        Parameters
        ----------
        node : ast.FunctionDef
            FunctionDef AST node.
        """
        qname = self._qualify(node.name)
        docstring = ast.get_docstring(node, clean=False)
        self.symbols.append(_CollectedSymbol(qname, node, "function", docstring))
        self.namespace.append(node.name)
        self.generic_visit(node)
        self.namespace.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition and collect symbol.

        Parameters
        ----------
        node : ast.AsyncFunctionDef
            AsyncFunctionDef AST node.
        """
        qname = self._qualify(node.name)
        docstring = ast.get_docstring(node, clean=False)
        self.symbols.append(_CollectedSymbol(qname, node, "function", docstring))
        self.namespace.append(node.name)
        self.generic_visit(node)
        self.namespace.pop()


def _display_name_for(kind: ParameterKind, name: str) -> str:
    if kind == "var_positional":
        return f"*{name}"
    if kind == "var_keyword":
        return f"**{name}"
    return name


def _is_variadic_parameter(parameter: DocstringIRParameter) -> bool:
    return parameter.kind in {"var_positional", "var_keyword"}


def annotation_to_text(annotation: ast.AST | None) -> str | None:
    """Convert an annotation node to source text.

    Parameters
    ----------
    annotation : ast.AST | None
        AST annotation node.

    Returns
    -------
    str | None
        Source text representation of the annotation, or None if conversion fails.
    """
    if annotation is None:
        return None
    try:
        return ast.unparse(annotation)
    except AttributeError:  # pragma: no cover - Python <3.9 fallback
        fallback: object = getattr(annotation, "id", None)
        return fallback if isinstance(fallback, str) else None


def _default_to_text(default: ast.AST | None) -> str | None:
    if default is None:
        return None
    try:
        return ast.unparse(default)
    except AttributeError:  # pragma: no cover - Python <3.9 fallback
        fallback: object = getattr(default, "id", None)
        return fallback if isinstance(fallback, str) else None


def _make_parameter(
    arg: ast.arg,
    default: ast.AST | None,
    *,
    kind: ParameterKind,
) -> DocstringIRParameter:
    annotation_text = annotation_to_text(arg.annotation)
    default_text = _default_to_text(default)
    is_variadic = kind in {"var_positional", "var_keyword"}
    optional = default is not None and not is_variadic
    return DocstringIRParameter(
        name=arg.arg,
        display_name=_display_name_for(kind, arg.arg),
        kind=kind,
        annotation=annotation_text,
        default=default_text,
        optional=optional,
        description="",
    )


def parameters_for(node: ast.AST) -> list[DocstringIRParameter]:
    """Return parameter metadata for function or method nodes.

    Parameters
    ----------
    node : ast.AST
        AST node (must be FunctionDef or AsyncFunctionDef).

    Returns
    -------
    list[DocstringIRParameter]
        List of parameter metadata, empty if node is not a function/method.
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    params: list[DocstringIRParameter] = []
    arguments = node.args

    def handle_parameters(
        items: list[ast.arg],
        defaults: Sequence[ast.expr | None],
        *,
        kind: ParameterKind,
    ) -> None:
        """Process parameter arguments and defaults.

        Parameters
        ----------
        items : list[ast.arg]
            Parameter argument nodes.
        defaults : Sequence[ast.expr | None]
            Default value expressions.
        kind : ParameterKind
            Parameter kind (positional_only, positional_or_keyword, etc.).
        """
        padding = len(items) - len(defaults)
        padded_defaults: list[ast.AST | None] = [None] * padding
        padded_defaults.extend(cast("ast.AST | None", default) for default in defaults)
        for arg, default_value in zip(items, padded_defaults, strict=True):
            params.append(_make_parameter(arg, default_value, kind=kind))

    handle_parameters(arguments.posonlyargs, [], kind="positional_only")
    handle_parameters(arguments.args, list(arguments.defaults), kind="positional_or_keyword")
    if arguments.vararg is not None:
        params.append(
            _make_parameter(
                arguments.vararg,
                None,
                kind="var_positional",
            )
        )
    handle_parameters(arguments.kwonlyargs, list(arguments.kw_defaults), kind="keyword_only")
    if arguments.kwarg is not None:
        params.append(
            _make_parameter(
                arguments.kwarg,
                None,
                kind="var_keyword",
            )
        )
    return params


def module_name_for(file_path: Path) -> str:
    """Return the dotted module path for a file.

    Parameters
    ----------
    file_path : Path
        Filesystem path to a Python file.

    Returns
    -------
    str
        Dotted module name (e.g., "tools.docstring_builder").
    """
    resolved = file_path.resolve()
    config = LegacyConfig()
    src_root = config.src_root
    repo_root = config.repo_root
    if src_root in resolved.parents or resolved == src_root:
        relative = resolved.relative_to(src_root)
    elif repo_root in resolved.parents or resolved == repo_root:
        relative = resolved.relative_to(repo_root)
    else:
        relative = resolved
    dotted = ".".join(relative.with_suffix("").parts)
    if dotted.endswith(".__init__"):
        dotted = dotted.rsplit(".", 1)[0]
    return dotted


def _normalize_qualified_name(name: str) -> str:
    """Canonicalise a fully-qualified name using the override catalogue.

    Parameters
    ----------
    name : str
        Qualified name to normalize.

    Returns
    -------
    str
        Normalized name using override mappings.
    """
    base = name.split("[", 1)[0]
    return QUALIFIED_NAME_OVERRIDES.get(base, base)


def normalize_qualified_name(name: str) -> str:
    """Canonicalise a fully-qualified name using the override catalogue.

    Parameters
    ----------
    name : str
        Qualified name to normalize.

    Returns
    -------
    str
        Normalized name using override mappings.
    """
    return _normalize_qualified_name(name)


def _wrap_text(text: str) -> list[str]:
    wrapped: list[str] = []
    for raw_paragraph in text.splitlines():
        paragraph = raw_paragraph.strip()
        if not paragraph:
            wrapped.append("")
            continue
        wrapped.append(
            textwrap.fill(paragraph, width=88, break_long_words=False, break_on_hyphens=False)
        )
    while wrapped and not wrapped[-1]:
        wrapped.pop()
    return wrapped


def _format_parameter_entry(param: DocstringIRParameter) -> tuple[str, str]:
    annotation = param.annotation or "Any"
    optional_suffix = ", optional" if param.optional and not _is_variadic_parameter(param) else ""
    default_suffix = f", by default {param.default}" if param.default not in {None, "..."} else ""
    header = f"{param.display_name} : {annotation}{optional_suffix}{default_suffix}"
    body = f"    Description for ``{param.name}``."
    return header, body


def _required_sections(context: _RequiredSectionsContext) -> list[str]:
    """Return the ordered docstring section headers required for a symbol.

    Parameters
    ----------
    context : _RequiredSectionsContext
        Context containing symbol metadata.

    Returns
    -------
    list[str]
        Ordered list of section headers (e.g., ["Parameters", "Returns", "Raises"]).
    """
    required: list[str] = []
    if context.parameters:
        required.append("Parameters")
    if context.returns_annotation and context.returns_annotation != "None":
        required.append("Returns")
    if context.raises:
        required.append("Raises")
    if context.kind == "function" and context.is_public:
        required.append("Examples")
    return required


def required_sections(
    kind: str,
    parameters: Sequence[DocstringIRParameter],
    returns: str | None,
    raises: Sequence[str],
    *,
    is_public: bool,
    **_: object,
) -> list[str]:
    """Return the ordered docstring sections for a symbol description.

    Parameters
    ----------
    kind : str
        Symbol kind (e.g., "function", "class").
    parameters : Sequence[DocstringIRParameter]
        Parameter metadata.
    returns : str | None
        Return annotation text.
    raises : Sequence[str]
        Exception names raised.
    is_public : bool
        Whether the symbol is public (doesn't start with underscore).
    **_ : object
        Additional keyword arguments (ignored).

    Returns
    -------
    list[str]
        Ordered list of section headers required for the symbol.
    """
    context = _RequiredSectionsContext(
        kind=kind,
        parameters=list(parameters),
        returns_annotation=returns,
        raises=list(raises),
        is_public=is_public,
    )
    return _required_sections(context)


def build_examples(context: _ExampleContext) -> list[str]:
    """Generate doctest-style examples for a callable.

    Parameters
    ----------
    context : _ExampleContext
        Context containing symbol metadata for example generation.

    Returns
    -------
    list[str]
        List of doctest-style example lines.
    """
    lines: list[str] = []
    if context.include_import and context.module_name:
        lines.append(f">>> from {context.module_name} import {context.name}")

    call_parts: list[str] = []
    trailing_parts: list[str] = []
    for param in context.parameters:
        if param.kind == "var_positional":
            trailing_parts.append(f"*{param.name}")
        elif param.kind == "var_keyword":
            trailing_parts.append(f"**{param.name}")
        elif not param.optional:
            call_parts.append("...")
    call_parts.extend(trailing_parts)
    call_fragment = ", ".join(call_parts)
    invocation = f"{context.name}({call_fragment})" if call_fragment else f"{context.name}()"

    if context.is_async:
        lines.append(f">>> result = {invocation}")
        lines.append(">>> result  # doctest: +ELLIPSIS")
        lines.append("...")
        return lines

    if context.returns_value:
        lines.append(f">>> result = {invocation}")
        lines.append(">>> result  # doctest: +ELLIPSIS")
    else:
        lines.append(f">>> {invocation}  # doctest: +ELLIPSIS")
    return lines


def _extract_exception_name(exc: ast.AST | None) -> str | None:
    """Return the exception name for a raise expression.

    Parameters
    ----------
    exc : ast.AST | None
        Exception AST node.

    Returns
    -------
    str | None
        Exception name if extractable, None otherwise.
    """
    if exc is None:
        return None
    if isinstance(exc, ast.Name):
        return exc.id
    if isinstance(exc, ast.Attribute):
        return exc.attr
    if isinstance(exc, ast.Call):
        return _extract_exception_name(exc.func)
    return None


def _child_blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    """Return child statement blocks that should be inspected for raises.

    Parameters
    ----------
    statement : ast.stmt
        Statement node to extract child blocks from.

    Returns
    -------
    list[list[ast.stmt]]
        List of child statement blocks (e.g., body, orelse, handlers).
    """
    if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return [statement.body, statement.orelse]
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return [statement.body]
    if isinstance(statement, ast.Try):
        blocks = [statement.body, statement.orelse, statement.finalbody]
        blocks.extend(handler.body for handler in statement.handlers)
        return blocks
    if isinstance(statement, ast.Match):
        return [case.body for case in statement.cases]
    return []


def detect_raises(node: ast.AST) -> list[str]:
    """Detect top-level exceptions raised by a callable.

    Parameters
    ----------
    node : ast.AST
        AST node (must be FunctionDef or AsyncFunctionDef).

    Returns
    -------
    list[str]
        List of exception names raised by the callable.
    """
    raises: list[str] = []
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return raises

    stack: list[ast.stmt] = list(reversed(node.body))
    skip_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

    while stack:
        current = stack.pop()
        if isinstance(current, ast.Raise):
            name = _extract_exception_name(current.exc)
            if name and name not in raises:
                raises.append(name)
            continue
        if isinstance(current, skip_types):
            continue
        for block in _child_blocks(current):
            stack.extend(reversed(block))

    return raises


def extended_summary(kind: str, name: str, module: str, node: ast.AST | None = None) -> str:
    """Return the extended summary paragraph for the symbol.

    Parameters
    ----------
    kind : str
        Symbol kind (e.g., "function", "class").
    name : str
        Symbol name.
    module : str
        Module name.
    node : ast.AST | None, optional
        AST node for additional context.

    Returns
    -------
    str
        Extended summary paragraph text.
    """
    return overrides_extended_summary(kind, name, module, node)


def summarize(kind: str, name: str) -> str:
    """Return the short summary sentence for the symbol.

    Parameters
    ----------
    kind : str
        Symbol kind (e.g., "function", "class").
    name : str
        Symbol name.

    Returns
    -------
    str
        Short summary sentence.
    """
    return overrides_summarize(name, kind)


def _is_magic(name: str) -> bool:
    """Return ``True`` when the provided callable is a Python magic method.

    Parameters
    ----------
    name : str
        Method name to check.

    Returns
    -------
    bool
        True if name is a magic method, False otherwise.
    """
    return overrides_is_magic(name)


def _is_pydantic_artifact(name: str) -> bool:
    """Return ``True`` when the provided name refers to a Pydantic helper.

    Parameters
    ----------
    name : str
        Method name to check.

    Returns
    -------
    bool
        True if name is a Pydantic artifact, False otherwise.
    """
    return overrides_is_pydantic_artifact(name)


def is_magic(name: str) -> bool:
    """Return ``True`` when the provided callable is a Python magic method.

    Parameters
    ----------
    name : str
        Method name to check.

    Returns
    -------
    bool
        True if name is a magic method, False otherwise.
    """
    return _is_magic(name)


def is_pydantic_artifact(name: str) -> bool:
    """Return ``True`` when the provided name refers to a Pydantic helper.

    Parameters
    ----------
    name : str
        Method name to check.

    Returns
    -------
    bool
        True if name is a Pydantic artifact, False otherwise.
    """
    return _is_pydantic_artifact(name)


def build_docstring(
    kind: str, node: ast.FunctionDef | ast.AsyncFunctionDef, module_name: str
) -> list[str]:
    """Build a NumPy style docstring as a list of lines.

    Parameters
    ----------
    kind : str
        Symbol kind (e.g., "function", "method").
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function AST node.
    module_name : str
        Module name for context.

    Returns
    -------
    list[str]
        List of docstring lines including triple quotes.
    """
    name = node.name
    is_public = not name.startswith("_")
    params = parameters_for(node)
    returns_text = annotation_to_text(node.returns)
    raises = detect_raises(node)
    summary = summarize(kind, name)
    extended = extended_summary(kind, name, module_name, node)
    is_async = isinstance(node, ast.AsyncFunctionDef)
    returns_value = returns_text not in {None, "None"}

    lines: list[str] = ['"""', summary, DEFAULT_MARKER]

    if extended:
        lines.append("")
        lines.extend(_wrap_text(extended))

    if params:
        lines.append("")
        lines.append("Parameters")
        lines.append("----------")
        for header, body in (_format_parameter_entry(param) for param in params):
            lines.append(header)
            lines.append(body)

    if returns_value:
        lines.append("")
        lines.append("Returns")
        lines.append("-------")
        lines.append(returns_text or "Any")
        lines.append("    Describe the returned value.")

    if raises:
        lines.append("")
        lines.append("Raises")
        lines.append("------")
        for exc in raises:
            lines.append(exc)
            lines.append(f"    Raised when ``{exc}`` is encountered.")

    if kind == "function" and is_public:
        examples = build_examples(
            _ExampleContext(
                module_name=module_name,
                name=name,
                parameters=params,
                include_import=True,
                is_async=is_async,
                returns_value=returns_value,
            )
        )
        if examples:
            lines.append("")
            lines.append("Examples")
            lines.append("--------")
            lines.append("")
            lines.extend(examples)

    lines.append('"""')
    return lines


def _lines_to_docstring_text(lines: list[str]) -> str:
    """Transform emitted docstring lines into the inner text payload.

    Parameters
    ----------
    lines : list[str]
        List of docstring lines including opening/closing triple quotes.

    Returns
    -------
    str
        Inner text content of the docstring (excluding quotes).

    Raises
    ------
    ValueError
        If the lines don't start with triple quotes.
    """
    opening = lines[0]
    if not opening.startswith('"""'):
        message = "Docstring must start with triple quotes."
        raise ValueError(message)
    core_lines = ["", *lines[1:-1]]
    text = "\n".join(core_lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


def process_file(file_path: Path) -> bool:
    """Generate docstrings for the supplied module.

    Parameters
    ----------
    file_path : Path
        Path to the Python file to process.

    Returns
    -------
    bool
        True if docstrings were generated and applied, False otherwise.
    """
    module_name = module_name_for(file_path)
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    collector = _SymbolCollector(module_name)
    collector.visit(tree)

    edits: list[DocstringEdit] = []
    for symbol in collector.symbols:
        if symbol.kind != "function":
            continue
        if not isinstance(symbol.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = symbol.docstring or ""
        if doc and DEFAULT_MARKER not in doc:
            continue
        doc_lines = build_docstring(symbol.kind, symbol.node, module_name)
        doc_text = _lines_to_docstring_text(doc_lines)
        edits.append(DocstringEdit(qname=symbol.qname, text=doc_text))

    if not edits:
        return False

    result = HarvestResult(module=module_name, filepath=file_path, symbols=[], cst_index={})
    changed, _ = apply_edits(result, edits)
    if changed:
        _ensure_trailing_blank_lines(file_path)
    return changed


def _ensure_trailing_blank_lines(file_path: Path) -> None:
    """Ensure generated docstrings leave a spacer line after the closing quotes."""
    lines = file_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return
    new_lines: list[str] = []
    pending_marker = False
    for index, line in enumerate(lines):
        new_lines.append(line)
        if DEFAULT_MARKER in line:
            pending_marker = True
        if line.strip() != '"""':
            continue
        if not pending_marker:
            continue
        next_index = index + 1
        if next_index >= len(lines) or lines[next_index].strip():
            new_lines.append("")
        pending_marker = False
    file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


__all__ = [
    "DEFAULT_MAGIC_METHOD_FALLBACK",
    "DEFAULT_PYDANTIC_ARTIFACT_SUMMARY",
    "MAGIC_METHOD_EXTENDED_SUMMARIES",
    "PYDANTIC_ARTIFACT_SUMMARIES",
    "QUALIFIED_NAME_OVERRIDES",
    "STANDARD_METHOD_EXTENDED_SUMMARIES",
    "_STANDARD_METHOD_EXTENDED_SUMMARIES",
    "_RequiredSectionsContext",
    "_is_magic",
    "_is_pydantic_artifact",
    "_normalize_qualified_name",
    "_required_sections",
    "annotation_to_text",
    "build_docstring",
    "build_examples",
    "configure_roots",
    "detect_raises",
    "extended_summary",
    "is_magic",
    "is_pydantic_artifact",
    "module_name_for",
    "normalize_qualified_name",
    "parameters_for",
    "process_file",
    "required_sections",
    "summarize",
]
