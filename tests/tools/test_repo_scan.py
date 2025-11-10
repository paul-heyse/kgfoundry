from __future__ import annotations

import json
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from tools import repo_scan


def _run_repo_scan_cli(
    monkeypatch: pytest.MonkeyPatch,
    scan_root: Path,
    tmp_path: Path,
    extra_args: list[str] | None = None,
) -> tuple[dict[str, Any], Path]:
    """Invoke repo_scan.main() with the provided arguments and return its payload.

    Returns
    -------
    tuple[dict[str, object], Path]
        Parsed JSON payload and the path to the generated DOT file.
    """
    json_path = tmp_path / "metrics.json"
    dot_path = tmp_path / "graph.dot"
    argv = [
        "repo_scan.py",
        str(scan_root),
        "--repo-root",
        str(scan_root),
        "--out-json",
        str(json_path),
        "--out-dot",
        str(dot_path),
    ]
    if extra_args:
        argv.extend(extra_args)
    monkeypatch.setattr(sys, "argv", argv)
    repo_scan.main()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    return payload, dot_path


def test_iter_py_files_skips_virtual_env_content(tmp_path: Path) -> None:
    """Ensure skip rules prevent generated folders from polluting metrics."""
    root = tmp_path / "workspace"
    root.mkdir()
    keep = root / "pkg" / "module.py"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("VALUE = 1\n", encoding="utf-8")

    skip = root / ".venv" / "module.py"
    skip.parent.mkdir(parents=True, exist_ok=True)
    skip.write_text("SHOULD_SKIP = True\n", encoding="utf-8")

    discovered = {path.relative_to(root) for path in repo_scan.iter_py_files(root)}
    assert Path("pkg/module.py") in discovered
    assert Path(".venv/module.py") not in discovered


def test_iter_py_files_include_subdir_filters(tmp_path: Path) -> None:
    """Restrict scanning to the requested subdirectories."""
    root = tmp_path / "workspace"
    (root / "src" / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "src" / "pkg" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_pkg.py").write_text("VALUE = 2\n", encoding="utf-8")

    discovered = {
        path.relative_to(root) for path in repo_scan.iter_py_files(root, include_subdirs=("src",))
    }
    assert Path("src/pkg/module.py") in discovered
    assert Path("tests/test_pkg.py") not in discovered


@pytest.mark.parametrize(
    ("relative_parts", "module_name", "expected"),
    [
        (("tests", "unit_test.py"), "tests.unit_test", True),
        (("pkg", "test_adapter.py"), "pkg.test_adapter", True),
        (("pkg", "adapter_test.py"), "pkg.adapter_test", True),
        (("pkg", "adapter.py"), "pkg.adapter", False),
    ],
)
def test_is_test_file_heuristics(
    tmp_path: Path, relative_parts: tuple[str, ...], module_name: str, *, expected: bool
) -> None:
    """Confirm the test-file heuristic covers path- and name-based patterns."""
    file_path = tmp_path.joinpath(*relative_parts)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("CONST = 1\n", encoding="utf-8")
    assert repo_scan.is_test_file(file_path, module_name) is expected


def test_repo_scan_main_generates_expected_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the CLI end-to-end on a synthetic repo to validate the payload shape."""
    scan_root = tmp_path / "scan"
    src_dir = scan_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    pkg_dir = src_dir / "pkg"
    tests_dir = scan_root / "tests"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (pkg_dir / "__init__.py").write_text(
        dedent(
            '''\
            """Package entry point used by the repo scan test."""

            from . import mod_a

            __all__ = ["public_func"]


            def public_func(value: int) -> int:
                """Return the provided value to ensure public API detection works."""
                return mod_a.helper(value, 0)
            '''
        ),
        encoding="utf-8",
    )
    (pkg_dir / "mod_a.py").write_text(
        dedent(
            '''\
            """Supporting module with annotated functions and classes."""

            class Demo:
                """Sample class to drive docstring counters."""

                def describe(self, flag: bool) -> str:
                    """Return a string documenting the branch counting logic."""
                    if flag:
                        return "truthy"
                    return "falsey"


            def helper(lhs: int, rhs: int) -> int:
                """Provide deterministic arithmetic for the test repo."""
                if lhs > rhs:
                    return lhs - rhs
                return rhs - lhs
            '''
        ),
        encoding="utf-8",
    )
    (tests_dir / "test_pkg.py").write_text(
        dedent(
            """\
            \"\"\"Test module that imports the package to mimic repo usage.\"\"\"

            from pkg import mod_a


            def test_helper_round_trip() -> None:
                \"\"\"Ensure the helper behavior lines up with expectations.\"\"\"

                assert mod_a.helper(3, 1) == 2
            """
        ),
        encoding="utf-8",
    )

    payload, dot_path = _run_repo_scan_cli(monkeypatch, scan_root, tmp_path)
    modules = {entry["module"]: entry for entry in payload["modules"]}

    assert payload["summary"] == {"files": 3, "parsed_ok": 3, "tests": 1}
    assert modules["pkg"]["doc"]["module_doc"] is True
    assert modules["pkg.mod_a"]["typing"]["functions"] >= 1
    assert payload["api_symbols"] == []
    assert payload["external_deps"] == []

    edge_set = {tuple(edge) for edge in payload["import_edges"]}
    assert ("pkg", "pkg.mod_a") in edge_set

    assert payload["tests_to_modules"]["pkg"] == ["tests.test_pkg"]
    assert Path(dot_path).read_text(encoding="utf-8").startswith("digraph imports")


def test_module_name_strips_src_prefix(tmp_path: Path) -> None:
    """Ensure module names drop the leading `src` segment by default."""
    scan_root = tmp_path / "workspace"
    target = scan_root / "src" / "pkg" / "mod.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")

    name = repo_scan.module_name_from_path(scan_root, target, strip_prefixes=("src",))
    assert name == "pkg.mod"


def test_repo_scan_with_libcst_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure LibCST wiring enriches module reports and external dependency summary."""
    pytest.importorskip("libcst")
    scan_root = tmp_path / "libcst_scan"
    mod_path = scan_root / "pkg" / "mod.py"
    mod_path.parent.mkdir(parents=True, exist_ok=True)
    mod_path.write_text(
        dedent(
            """\
            import json as json_alias
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from vendor.tools import FancyType
            """
        ),
        encoding="utf-8",
    )

    payload, _ = _run_repo_scan_cli(monkeypatch, scan_root, tmp_path, ["--with-libcst"])
    modules = {entry["module"]: entry for entry in payload["modules"]}
    module_report = modules["pkg.mod"]
    assert module_report["imports_cst"] is not None
    assert "json_alias" in module_report["imports_cst"]["imports"]
    assert module_report["imports_cst"]["type_checking_imports"] == ["vendor.tools.FancyType"]
    assert "json" in payload["external_deps"]
    assert "vendor" in payload["external_deps"]


def test_repo_scan_with_griffe_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm Griffe-powered API extraction populates api_symbols."""
    pytest.importorskip("griffe")
    scan_root = tmp_path / "griffe_scan"
    pkg_dir = scan_root / "pkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text(
        dedent(
            '''\
            """Greeter package."""

            class Greeter:
                """Greet callers in a friendly way."""

                def __init__(self, prefix: str) -> None:
                    """Store the greeting prefix."""
                    self._prefix = prefix

                def greet(self, name: str) -> str:
                    """Compose a greeting.

                    Args
                    ----
                    name
                        Person to greet.

                    Returns
                    -------
                    str
                        Personalized greeting.
                    """
                    return f"{self._prefix} {name}"
            '''
        ),
        encoding="utf-8",
    )

    payload, _ = _run_repo_scan_cli(
        monkeypatch,
        scan_root,
        tmp_path,
        ["--with-griffe", "--docstyle", "google"],
    )
    assert payload["api_symbols"], "Expected Griffe symbols to be emitted"
    greeter_symbol = next((s for s in payload["api_symbols"] if s["short_name"] == "Greeter"), None)
    assert greeter_symbol is not None
    assert any(param["name"] == "prefix" for param in greeter_symbol["params"])
