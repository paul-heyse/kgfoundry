"""Consolidated typing façade and gate-import contract tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from codeintel_rev.typing import LoggerLike, NDArrayF32, NDArrayI64, PathLike

from kgfoundry_common.typing import (
    JSONValue,
    NavMap,
    ProblemDetails,
    SymbolID,
    override_gate_import,
    resolve_faiss,
    resolve_fastapi,
    resolve_numpy,
    safe_get_type,
)
from tests._helpers import assertions
from tests.helpers.typing_facades import load_facade_attribute_typed, load_facade_module


def _module_available(module_name: str) -> bool:
    """Return True if a module can be imported.

    Parameters
    ----------
    module_name : str
        Dotted module path to import.

    Returns
    -------
    bool
        True when the module import succeeds, False otherwise.
    """
    try:
        load_facade_module(module_name)
    except ImportError:
        return False
    return True


def _read_source(module: ModuleType) -> str:
    """Return the source text for a loaded module.

    Parameters
    ----------
    module : ModuleType
        Loaded module whose source is being inspected.

    Returns
    -------
    str
        Source text of the module.
    """
    source_path = Path(module.__file__ or "")
    assertions.expect_true(source_path.exists(), reason="module should have __file__ attribute")
    return source_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "module_name",
    [
        "kgfoundry_common.typing",
        "tools.typing",
        pytest.param(
            "docs.typing",
            marks=pytest.mark.skipif(
                not _module_available("docs.typing"),
                reason="docs.typing not installed",
            ),
        ),
    ],
)
def test_facade_sources_use_postponed_annotations(module_name: str) -> None:
    """All façade modules must enable postponed annotations and TYPE_CHECKING guards."""
    module = load_facade_module(module_name)
    content = _read_source(module)
    assertions.expect_in("from __future__ import annotations", content)
    assertions.expect_in("if TYPE_CHECKING:", content)


def test_common_facade_has_no_eager_numpy_imports() -> None:
    """kgfoundry_common.typing should not import numpy outside TYPE_CHECKING."""
    module = load_facade_module("kgfoundry_common.typing")
    content = _read_source(module)
    lines = content.splitlines()
    for index, line in enumerate(lines, start=1):
        if "if TYPE_CHECKING:" in line:
            break
        stripped = line.strip()
        if stripped.startswith(("import numpy", "from numpy")):
            pytest.fail(f"Found unguarded numpy import at line {index}")


def test_gate_import_happy_path_and_errors() -> None:
    """gate_import should cache successes and surface purpose in failures."""
    gate_import = load_facade_attribute_typed(
        "kgfoundry_common.typing",
        "gate_import",
        Callable,
    )

    json_mod = gate_import("json", "typing contract test")
    assertions.expect_true(hasattr(json_mod, "loads"))

    json_mod_second = gate_import("json", "repeat import")
    assertions.expect_true(json_mod is json_mod_second)

    purpose = "missing module for typing contract"
    with pytest.raises(ImportError) as exc_info:
        gate_import("nonexistent_fake_module", purpose)
    message = str(exc_info.value)
    assertions.expect_in("nonexistent_fake_module", message)
    assertions.expect_in(purpose, message)
    assertions.expect_in("pip install", message)


def test_safe_get_type_variants() -> None:
    """safe_get_type returns expected values for present, missing, and default cases."""
    list_type = safe_get_type("builtins", "list")
    assertions.expect_true(list_type is list)

    assertions.expect_equal(safe_get_type("nonexistent_xyz", "SomeType"), None)
    assertions.expect_equal(safe_get_type("json", "NonexistentType"), None)

    default = "fallback"
    assertions.expect_equal(
        safe_get_type("nonexistent", "Something", default=default),
        default,
    )


@pytest.mark.parametrize(
    ("resolver", "module_name"),
    [
        (resolve_numpy, "numpy"),
        (resolve_fastapi, "fastapi"),
    ],
)
def test_resolve_shims_emit_warnings(resolver: Callable[[], ModuleType], module_name: str) -> None:
    """resolve_* helpers should warn and return the underlying module."""
    with pytest.warns(DeprecationWarning, match=r"deprecated"):
        module = resolver()
    assertions.expect_true(isinstance(module, ModuleType))
    assertions.expect_true(module.__name__ == module_name)


def test_resolve_faiss_emits_warning_and_returns_module() -> None:
    """resolve_faiss should warn and return the resolved module."""
    with (
        override_gate_import({"faiss": ModuleType("faiss")}),
        pytest.warns(DeprecationWarning, match=r"deprecated"),
    ):
        module = resolve_faiss()
    assertions.expect_true(isinstance(module, ModuleType))
    assertions.expect_true(hasattr(module, "__name__"))


def test_alias_exports_are_available() -> None:
    """Type aliases should be exported from the façade."""
    assertions.expect_true(NavMap is not None)
    assertions.expect_true(ProblemDetails is not None)
    assertions.expect_true(JSONValue is not None)
    assertions.expect_true(SymbolID is not None)


def test_protocol_and_array_aliases() -> None:
    """Protocol and ndarray aliases should accept representative values."""
    logger = _DummyLogger()
    assertions.expect_true(isinstance(logger, LoggerLike))

    path_value: PathLike = Path("artifact")
    assertions.expect_true(isinstance(path_value, Path))

    assertions.expect_true(NDArrayF32 is not None)
    assertions.expect_true(NDArrayI64 is not None)


def test_gate_import_is_reexported_from_facades() -> None:
    """gate_import should be re-exported consistently across façade modules."""
    common_gate = load_facade_attribute_typed(
        "kgfoundry_common.typing",
        "gate_import",
        Callable,
    )
    tools_gate = load_facade_attribute_typed("tools.typing", "gate_import", Callable)
    assertions.expect_true(common_gate is tools_gate)

    if _module_available("docs.typing"):
        docs_gate = load_facade_attribute_typed("docs.typing", "gate_import", Callable)
        assertions.expect_true(common_gate is docs_gate)


class _DummyLogger:
    """Test logger that records the last logging call."""

    def __init__(self) -> None:
        self.last_call: tuple[str, str, tuple[object, ...], dict[str, object]] | None = None

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        self.last_call = ("debug", msg, args, kwargs)

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        self.last_call = ("info", msg, args, kwargs)

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        self.last_call = ("warning", msg, args, kwargs)

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        self.last_call = ("error", msg, args, kwargs)
