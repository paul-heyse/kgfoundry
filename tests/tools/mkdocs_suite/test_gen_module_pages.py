"""Tests for the MkDocs module page generator helpers."""

from __future__ import annotations

import ast
import importlib
import importlib.machinery
import importlib.util
import io
import logging
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import griffe
import pytest

augment_registry: types.ModuleType = importlib.import_module("tools._shared.augment_registry")


def _make_module(name: str, *, package: bool = False) -> types.ModuleType:
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    return module


def _install_mkdocs_gen_files_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_module = _make_module("mkdocs_gen_files")
    stub = cast("Any", stub_module)
    stub.open = lambda *_args, **_kwargs: io.StringIO()
    stub.files = io.StringIO
    monkeypatch.setitem(sys.modules, "mkdocs_gen_files", stub_module)


def _install_tooling_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "tools", _make_module("tools", package=True))
    monkeypatch.setitem(sys.modules, "tools._shared", _make_module("tools._shared", package=True))
    monkeypatch.setitem(
        sys.modules,
        "tools.mkdocs_suite",
        _make_module("tools.mkdocs_suite", package=True),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.mkdocs_suite.docs",
        _make_module("tools.mkdocs_suite.docs", package=True),
    )


def _install_augment_registry_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_module = _make_module("tools._shared.augment_registry")
    stub = cast("Any", stub_module)
    stub.AugmentRegistryError = type("AugmentRegistryError", (Exception,), {})
    stub.load_registry = lambda *_args, **_kwargs: None
    stub.render_problem_details = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "tools._shared.augment_registry", stub_module)


def _install_operation_links_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_module = _make_module("tools.mkdocs_suite.docs._scripts._operation_links")
    stub = cast("Any", stub_module)
    stub.build_operation_href = lambda *_args, **_kwargs: None
    monkeypatch.setitem(
        sys.modules,
        "tools.mkdocs_suite.docs._scripts._operation_links",
        stub_module,
    )


def _install_docs_scripts_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_module = _make_module("tools.mkdocs_suite.docs._scripts", package=True)
    stub = cast("Any", stub_module)
    stub.load_repo_settings = lambda *_args, **_kwargs: (None, None)
    monkeypatch.setitem(sys.modules, "tools.mkdocs_suite.docs._scripts", stub_module)


def _install_msgspec_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_module = _make_module("msgspec")
    stub = cast("Any", stub_module)

    class _Struct:
        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__(**kwargs)

    stub.Struct = _Struct
    stub.UNSET = object()
    stub.structs = types.SimpleNamespace(replace=lambda obj, **_kwargs: obj)
    stub.field = lambda *_args, **kwargs: kwargs
    stub.json = types.SimpleNamespace(
        encode=lambda *_args, **_kwargs: b"", decode=lambda *_args, **_kwargs: None
    )
    monkeypatch.setitem(sys.modules, "msgspec", stub_module)


def _install_kgfoundry_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "kgfoundry_common", _make_module("kgfoundry_common", package=True)
    )
    typing_stub_module = _make_module("kgfoundry_common.typing")
    typing_stub = cast("Any", typing_stub_module)
    typing_stub.gate_import = lambda *_args, **_kwargs: types.SimpleNamespace(
        ProblemDetailsDict=dict
    )
    monkeypatch.setitem(sys.modules, "kgfoundry_common.typing", typing_stub_module)

    errors_stub_module = _make_module("kgfoundry_common.errors")
    errors_stub = cast("Any", errors_stub_module)
    errors_stub.SchemaValidationError = type("SchemaValidationError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "kgfoundry_common.errors", errors_stub_module)

    serialization_stub_module = _make_module("kgfoundry_common.serialization")
    serialization_stub = cast("Any", serialization_stub_module)
    serialization_stub.validate_payload = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "kgfoundry_common.serialization", serialization_stub_module)

    logging_stub_module = _make_module("kgfoundry_common.logging")
    logging_stub = cast("Any", logging_stub_module)

    class _LoggerAdapter:
        def __init__(
            self, logger: object | None = None, extra: dict[str, object] | None = None
        ) -> None:
            self.logger = logger or types.SimpleNamespace()
            self.extra = extra or {}

    logging_stub.LoggerAdapter = _LoggerAdapter
    logging_stub.get_logger = lambda *_args, **_kwargs: _LoggerAdapter()
    monkeypatch.setitem(sys.modules, "kgfoundry_common.logging", logging_stub_module)


def _patch_importlib_for_navmap(monkeypatch: pytest.MonkeyPatch) -> None:
    original_spec = importlib.util.spec_from_file_location

    class _StubLoader(importlib.machinery.SourceFileLoader):
        def __init__(self, name: str, initializer: Callable[[types.ModuleType], None]) -> None:
            super().__init__(name, "<stub>")
            self._initializer = initializer

        def exec_module(self, module: types.ModuleType) -> None:
            self._initializer(module)

    def _navmap_initializer(module: types.ModuleType) -> None:
        module_any = cast("Any", module)
        module_any.DEFAULT_EXTENSIONS = []
        module_any.DEFAULT_SEARCH_PATHS = []

    def _nav_loader_initializer(module: types.ModuleType) -> None:
        module_any = cast("Any", module)
        module_any.load_nav_metadata = lambda *_args, **_kwargs: {}

        class _NavMetadataModel(dict):
            def as_mapping(self) -> dict[str, object]:
                return dict(self)

        module_any.NavMetadataModel = _NavMetadataModel

    def _fake_spec_from_file_location(
        name: str, location: str | Path, *args: Any, **kwargs: Any
    ) -> importlib.machinery.ModuleSpec:
        path_name = Path(location).name
        if path_name == "griffe_navmap.py":
            loader = _StubLoader(name, _navmap_initializer)
            return importlib.machinery.ModuleSpec(name, loader)
        if path_name == "navmap_loader.py":
            loader = _StubLoader(name, _nav_loader_initializer)
            return importlib.machinery.ModuleSpec(name, loader)
        spec = original_spec(name, location, *args, **kwargs)
        if spec is None or spec.loader is None:
            message = "Unable to construct module spec"
            raise RuntimeError(message)
        return spec

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec_from_file_location)


def _load_gen_module_pages_without_render(module_path: Path) -> types.ModuleType:
    module_code = module_path.read_text(encoding="utf-8")
    module_ast = ast.parse(module_code, filename=str(module_path))
    if module_ast.body:
        last_stmt = module_ast.body[-1]
        if isinstance(last_stmt, ast.Expr) and isinstance(last_stmt.value, ast.Call):
            call = last_stmt.value
            if getattr(call.func, "id", None) == "render_module_pages":
                module_ast.body.pop()

    compiled = compile(module_ast, str(module_path), "exec")

    class _PatchedLoader(importlib.machinery.SourceFileLoader):
        def __init__(self, fullname: str, path: str, code_obj: types.CodeType) -> None:
            super().__init__(fullname, path)
            self._code_obj = code_obj

        def get_code(self, fullname: str) -> types.CodeType:
            del fullname
            return self._code_obj

    module_name = "gen_module_pages_under_test"
    loader = _PatchedLoader(module_name, str(module_path), compiled)
    spec = importlib.util.spec_from_file_location(module_name, module_path, loader=loader)
    if spec is None or spec.loader is None:
        message = "Unable to construct module spec for gen_module_pages"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="gen_module_pages")
def fixture_gen_module_pages(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Load ``gen_module_pages`` without executing its expensive side effects.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest monkeypatch fixture for stubbing module imports.

    Returns
    -------
    types.ModuleType
        The loaded module instance with side effects stubbed out.
    """
    _install_mkdocs_gen_files_stub(monkeypatch)
    _install_tooling_namespace(monkeypatch)
    _install_augment_registry_stub(monkeypatch)
    _install_operation_links_stub(monkeypatch)
    _install_docs_scripts_stub(monkeypatch)
    _install_msgspec_stub(monkeypatch)
    _install_kgfoundry_stubs(monkeypatch)
    _patch_importlib_for_navmap(monkeypatch)

    module_path = (
        Path(__file__).resolve().parents[3]
        / "tools"
        / "mkdocs_suite"
        / "docs"
        / "_scripts"
        / "gen_module_pages.py"
    )
    return _load_gen_module_pages_without_render(module_path)


def test_inline_d2_neighborhood_uses_relative_doc_paths(
    gen_module_pages: types.ModuleType,
) -> None:
    """D2 neighborhood links should point to relative module documentation paths."""
    module_path = "kgfoundry_common.logging"
    ModuleFacts = gen_module_pages.ModuleFacts
    facts = ModuleFacts(
        imports={module_path: {"kgfoundry_common.config"}},
        imported_by={module_path: {"kgfoundry_common.app"}},
        exports={},
        classes={},
        functions={},
        bases={},
        api_usage={},
        documented_modules={
            module_path,
            "kgfoundry_common.config",
            "kgfoundry_common.app",
        },
        source_paths={},
    )

    inline_neighborhood = gen_module_pages.inline_d2_neighborhood
    block = inline_neighborhood(module_path, facts)

    assert 'link: "./kgfoundry_common/logging.md"' in block
    assert 'link: "./kgfoundry_common/config.md"' in block
    assert 'link: "./kgfoundry_common/app.md"' in block


def test_render_module_pages_warns_and_continues_on_invalid_api_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Invalid API usage JSON should be ignored with a warning during builds."""
    _install_mkdocs_gen_files_stub(monkeypatch)

    message = "stub discovery failure"

    def _raise_loader_error(*_args: object, **_kwargs: object) -> object:
        raise griffe.GriffeError(message)

    monkeypatch.setattr(griffe, "load", _raise_loader_error)
    monkeypatch.setattr(griffe, "load_extensions", lambda *_args, **_kwargs: [])

    # Prevent registry lookups from touching the filesystem during import.
    monkeypatch.setattr(augment_registry, "load_registry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(augment_registry, "render_problem_details", lambda _exc: {})

    module_name = "tools.mkdocs_suite.docs._scripts.gen_module_pages"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)

    caplog.clear()
    caplog.set_level(logging.WARNING, logger=module.LOGGER.name)

    invalid_file = tmp_path / "api_usage.json"
    invalid_file.write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(module, "API_USAGE_FILE", invalid_file)
    monkeypatch.setattr(module, "REGISTRY_PATH", tmp_path / "api_registry.yaml")

    discovered: dict[str, bool] = {}

    def _stub_discover_extensions(*_args: object, **_kwargs: object) -> tuple[list[str], None]:
        discovered["called"] = True
        return [], None

    monkeypatch.setattr(module, "_discover_extensions", _stub_discover_extensions)
    monkeypatch.setattr(module, "_collect_modules", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(module, "_render_module_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_nav_metadata_for_module", lambda *_args, **_kwargs: {})

    module.render_module_pages()

    assert discovered.get("called") is True
    assert any("Skipping API usage map" in record.message for record in caplog.records)
