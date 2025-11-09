"""Regression tests for MkDocs interface catalog generation."""

from __future__ import annotations

import importlib
import io
import json
import logging
import sys
import types
from pathlib import Path
from typing import Any, Self, cast

import pytest

MODULE_PATH = "tools.mkdocs_suite.docs._scripts.gen_interface_pages"


@pytest.fixture(name="temporary_repo")
def fixture_temporary_repo(tmp_path: Path) -> Path:
    """Create a temporary repository layout for nav discovery tests.

    Parameters
    ----------
    tmp_path : Path
        Pytest temporary directory fixture providing a base path for test files.

    Returns
    -------
    Path
        Path to the temporary repository root directory containing test
        navigation files.
    """
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "valid").mkdir(parents=True)
    (repo_root / "src" / "invalid").mkdir(parents=True)
    valid_nav = repo_root / "src" / "valid" / "_nav.json"
    invalid_nav = repo_root / "src" / "invalid" / "_nav.json"

    valid_payload = {"interfaces": [{"id": "valid-interface"}]}
    valid_nav.write_text(json.dumps(valid_payload), encoding="utf-8")
    invalid_nav.write_text("{not-json", encoding="utf-8")

    return repo_root


def test_collect_nav_interfaces_skips_malformed_json(
    temporary_repo: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed nav files should be ignored without raising errors."""
    caplog.set_level(logging.WARNING)
    module = importlib.import_module(MODULE_PATH)
    monkeypatch.setattr(module, "REPO_ROOT", temporary_repo)

    interfaces = module.collect_nav_interfaces()

    assert any("invalid/_nav.json" in record.message for record in caplog.records)
    assert interfaces == [{"id": "valid-interface", "module": "valid", "_nav_module_path": "valid"}]


class _DummyFile(io.StringIO):
    """Collect writes made through ``mkdocs_gen_files`` stubs."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Store written content keyed by the path before closing.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type if an exception occurred, None otherwise.
        exc_val : BaseException | None
            Exception value if an exception occurred, None otherwise.
        exc_tb : types.TracebackType | None
            Traceback object if an exception occurred, None otherwise.

        """
        _CAPTURED_OUTPUTS[self._path] = self.getvalue()


_CAPTURED_OUTPUTS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _clear_captured_outputs() -> None:
    _CAPTURED_OUTPUTS.clear()


def _install_mkdocs_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a lightweight ``mkdocs_gen_files`` shim for testing."""

    def _fake_open(path: object, *_args: object, **_kwargs: object) -> _DummyFile:
        return _DummyFile(str(path))

    stub_module = types.ModuleType("mkdocs_gen_files")
    stub = cast("Any", stub_module)
    stub.open = _fake_open
    stub.files = io.StringIO
    monkeypatch.setitem(sys.modules, "mkdocs_gen_files", stub_module)


def test_render_interface_catalog_links_full_module_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interfaces nested under packages should link using the full dotted path."""
    _install_mkdocs_stub(monkeypatch)
    module_name = "tools.mkdocs_suite.docs._scripts.gen_interface_pages"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    _CAPTURED_OUTPUTS.clear()

    src_pkg = tmp_path / "src" / "pkg_root" / "subpkg" / "leaf"
    src_pkg.mkdir(parents=True)
    nav_payload = {
        "interfaces": [
            {
                "id": "pkg.interfaces.Example",
                "type": "service",
            }
        ]
    }
    (src_pkg / "_nav.json").write_text(json.dumps(nav_payload), encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "REGISTRY_PATH", tmp_path / "api_registry.yaml")

    module.render_interface_catalog()

    output = _CAPTURED_OUTPUTS.get("api/interfaces.md")
    assert output is not None
    assert "pkg_root.subpkg.leaf" in output

    sys.modules.pop(module_name, None)


def test_render_interface_catalog_includes_module_source_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail sections should include module and source links when available."""
    _install_mkdocs_stub(monkeypatch)
    module_name = MODULE_PATH
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    _CAPTURED_OUTPUTS.clear()

    src_pkg = tmp_path / "src" / "pkg"
    src_pkg.mkdir(parents=True)
    (src_pkg / "module.py").write_text("# stub", encoding="utf-8")
    nav_payload = {
        "interfaces": [
            {
                "id": "pkg.interfaces.Service",
                "type": "service",
                "module": "pkg.module",
            }
        ]
    }
    (src_pkg / "_nav.json").write_text(json.dumps(nav_payload), encoding="utf-8")

    monkeypatch.setattr(module, "_load_registry", lambda: None)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "REPO_URL", "https://example.invalid/repo")
    monkeypatch.setattr(module, "DEFAULT_BRANCH", "main")

    module.render_interface_catalog()

    output = _CAPTURED_OUTPUTS.get("api/interfaces.md")
    assert output is not None
    assert "* **Module:** [pkg.module](../modules/pkg/module.md)" in output
    assert (
        "* **Source:** [pkg.module](https://example.invalid/repo/blob/main/src/pkg/module.py)"
        in output
    )

    sys.modules.pop(module_name, None)


def test_write_interface_table_escapes_markdown_control_characters() -> None:
    """User-controlled metadata should be escaped before inserting into tables."""
    handle = io.StringIO()
    interfaces: list[dict[str, object]] = [
        {
            "id": "interface|id\nwith newline",
            "type": "service|type",
            "module": "pkg.module",
            "owner": "owner|name`tick`",
            "stability": "beta|1",
            "spec": "http://example.com/spec|path",
            "description": "line1|\nline2`",
            "problem_details": ["issue|one", "issue`two`"],
        }
    ]

    module = importlib.import_module(MODULE_PATH)
    module.write_interface_table(handle, interfaces, registry=None)

    lines = handle.getvalue().strip().splitlines()
    row = lines[-1]
    cells = [cell.strip() for cell in row.strip().strip("|").split(" | ")]

    assert len(cells) == 8
    assert cells[0] == "interface\\|id<br />with newline"
    assert cells[1] == "service\\|type"
    assert cells[2] == "pkg.module"
    assert cells[3] == "owner\\|name\\`tick\\`"
    assert cells[4] == "beta\\|1"
    assert cells[5] == "http://example.com/spec\\|path"
    assert cells[6] == "line1\\|<br />line2\\`"
    assert cells[7] == "issue\\|one, issue\\`two\\`"


def test_operation_href_returns_relative_anchor(tmp_path: Path) -> None:
    """Operation links should include encoded anchors relative to the doc path."""
    monkeypatch = pytest.MonkeyPatch()
    try:
        _install_mkdocs_stub(monkeypatch)

        module = importlib.import_module(MODULE_PATH)
        monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(module, "REGISTRY_PATH", tmp_path / "registry.yaml")

        registry_stub = types.SimpleNamespace(
            interfaces={
                "pkg.interfaces.Example": types.SimpleNamespace(
                    type="service",
                    module="pkg.interfaces",
                    owner="owner",
                    stability="stable",
                    description=None,
                    spec="docs/api/openapi-cli.yaml",
                    operations={
                        "run": types.SimpleNamespace(
                            operation_id="cli.operation/with space",
                            summary="Summary",
                            handler="pkg.module:handler",
                            tags=[],
                            env=[],
                            problem_details=[],
                            extras={"code_samples": None},
                        )
                    },
                )
            },
            interface=lambda _identifier: None,
        )

        monkeypatch.setattr(module, "load_registry", lambda _path: registry_stub)

        (tmp_path / "src").mkdir()
        nav_dir = tmp_path / "src" / "pkg" / "interfaces"
        nav_dir.mkdir(parents=True)
        (nav_dir / "_nav.json").write_text(
            json.dumps(
                {
                    "interfaces": [
                        {
                            "id": "pkg.interfaces.Example",
                            "type": "service",
                            "spec": "docs/api/openapi-cli.yaml",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        _CAPTURED_OUTPUTS.clear()
        module.render_interface_catalog()
        rendered = "".join(_CAPTURED_OUTPUTS.values())
    finally:
        monkeypatch.undo()

    assert "openapi-cli.md#operation/cli.operation%2Fwith%20space" in rendered
