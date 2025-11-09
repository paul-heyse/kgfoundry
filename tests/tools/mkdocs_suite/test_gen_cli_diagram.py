from __future__ import annotations

import contextlib
import importlib
import io
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from tools.mkdocs_suite.docs.cli_diagram import collect_operations, write_diagram

if TYPE_CHECKING:
    from collections.abc import Iterator  # pragma: no cover - typing only

cli_tooling = importlib.import_module("tools._shared.cli_tooling")
AugmentConfig = cli_tooling.AugmentConfig
CLIToolingContext = cli_tooling.CLIToolingContext
RegistryContext = cli_tooling.RegistryContext


@contextlib.contextmanager
def _capture_write(
    buffers: dict[str, io.StringIO], path: str, mode: str
) -> Iterator[io.StringIO]:
    if "w" in mode:
        buffer = io.StringIO()
        buffers[path] = buffer
    else:
        if "r" in mode and path not in buffers:
            raise FileNotFoundError(path)
        buffer = buffers.setdefault(path, io.StringIO())
        if "r" in mode and "w" not in mode:
            buffer.seek(0)
        elif "a" in mode:
            buffer.seek(0, io.SEEK_END)
    yield buffer


def test_write_diagram_emits_single_node_for_multi_tag_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen_cli_module = importlib.import_module(
        "tools.mkdocs_suite.docs._scripts.gen_cli_diagram"
    )

    class DummyOperationContext:
        def build_operation(
            self, _tokens: list[str], _command: object
        ) -> tuple[str, dict[str, Any], list[str]]:
            return (
                "/cli/run",
                {
                    "operationId": "runCliCommand",
                    "summary": "Execute the CLI",
                    "tags": ["ingest", "admin", "ingest"],
                },
                ["ingest", "admin"],
            )

    class DummyCLIConfig:
        bin_name: ClassVar[str] = "kgf"
        interface_id: ClassVar[str] = "tools-cli"
        interface_meta: ClassVar[dict[str, str]] = {
            "entrypoint": "tests.fixtures.cli:app"
        }

        @property
        def operation_context(self) -> DummyOperationContext:
            return DummyOperationContext()

    augment_config = AugmentConfig.model_validate(
        {
            "path": Path("augment.yaml"),
            "payload": {"operations": {}},
        }
    )
    registry_context = RegistryContext.model_validate(
        {
            "path": Path("registry.yaml"),
            "interfaces": {
                "tools-cli": {"entrypoint": "tests.fixtures.cli:app"},
            },
        }
    )
    dummy_context = CLIToolingContext(
        augment=augment_config,
        registry=registry_context,
        cli_config=DummyCLIConfig(),
    )

    def fake_walk_commands(
        _command: object, _tokens: list[str]
    ) -> list[tuple[list[str], object]]:
        return [(["run"], object())]

    monkeypatch.setattr(gen_cli_module, "walk_commands", fake_walk_commands)

    operations = collect_operations(context=dummy_context, click_cmd=object())
    assert operations == [
        ("POST", "/cli/run", "runCliCommand", "Execute the CLI", ("ingest", "admin"))
    ]

    buffers: dict[str, io.StringIO] = {}

    def fake_open(
        path: str, mode: str = "r", **_: object
    ) -> contextlib.AbstractContextManager[io.StringIO]:
        return _capture_write(buffers, path, mode)

    monkeypatch.setattr(gen_cli_module.mkdocs_gen_files, "open", fake_open)

    write_diagram(operations)

    d2_output = buffers["diagrams/cli_by_tag.d2"].getvalue()

    assert d2_output.count('  "POST /cli/run":') == 1
    assert '  "ingest" -> "POST /cli/run"\n' in d2_output
    assert '  "admin" -> "POST /cli/run"\n' in d2_output


def test_write_diagram_escapes_special_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen_cli_module = importlib.import_module(
        "tools.mkdocs_suite.docs._scripts.gen_cli_diagram"
    )

    operations = [
        (
            "POST",
            '/cli/run "special"',
            'operation"Id',
            ('Summary "with" newline\nand backslash \\value'),
            ('core"ops', "line\\tag"),
        )
    ]

    buffers: dict[str, io.StringIO] = {}

    def fake_open(
        path: str, mode: str = "r", **_: object
    ) -> contextlib.AbstractContextManager[io.StringIO]:
        return _capture_write(buffers, path, mode)

    monkeypatch.setattr(gen_cli_module.mkdocs_gen_files, "open", fake_open)

    write_diagram(operations)

    output = buffers["diagrams/cli_by_tag.d2"].getvalue()

    assert '  "core\\"ops": "core\\"ops" {}' in output
    assert '  "line\\\\tag": "line\\\\tag" {}' in output
    assert (
        '  "POST /cli/run \\"special\\"": "POST /cli/run \\"special\\"\\n'
        'Summary \\"with\\" newline\\nand backslash \\\\value"'
        ' { link: "../api/openapi-cli.md#operation/operation\\"Id" }'
    ) in output


def test_collect_operations_surface_loader_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen_cli_module = importlib.import_module(
        "tools.mkdocs_suite.docs._scripts.gen_cli_diagram"
    )

    error_cls = gen_cli_module.CLIConfigError

    def failing_loader(*_: object, **__: object) -> None:
        raise error_cls(
            {
                "type": "https://kgfoundry.dev/problems/cli-config",
                "title": "CLI configuration error",
                "status": 404,
                "detail": "missing",
                "instance": "urn:test",
            }
        )

    monkeypatch.setattr(gen_cli_module, "load_cli_tooling_context", failing_loader)

    with pytest.raises(error_cls):
        collect_operations()


def test_ensure_cli_index_entry_preserves_existing_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen_cli_module = importlib.import_module(
        "tools.mkdocs_suite.docs._scripts.gen_cli_diagram"
    )

    existing_content = "- [Existing Diagram](./existing.d2)\n"
    buffers: dict[str, io.StringIO] = {
        gen_cli_module.DIAGRAM_INDEX_PATH: io.StringIO(existing_content)
    }
    open_calls: list[tuple[str, str]] = []

    @contextlib.contextmanager
    def fake_open(path: str, mode: str = "r", **_: object) -> Iterator[io.StringIO]:
        open_calls.append((path, mode))
        buffer = buffers.setdefault(path, io.StringIO())
        if "w" in mode:
            buffer = io.StringIO()
            buffers[path] = buffer
        elif "a" in mode:
            buffer.seek(0, io.SEEK_END)
        else:
            buffer.seek(0)
        yield buffer

    monkeypatch.setattr(gen_cli_module.mkdocs_gen_files, "open", fake_open)
    monkeypatch.setattr(gen_cli_module, "collect_operations", list)

    gen_cli_module.main()

    updated_content = buffers[gen_cli_module.DIAGRAM_INDEX_PATH].getvalue()
    # When no operations are discovered the existing content should remain unchanged.
    assert updated_content == existing_content

    read_modes = [
        mode
        for path, mode in open_calls
        if path == gen_cli_module.DIAGRAM_INDEX_PATH and "r" in mode
    ]
    assert read_modes == ["r"]


def test_update_cli_index_entry_preserves_double_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen_cli_module = importlib.import_module(
        "tools.mkdocs_suite.docs._scripts.gen_cli_diagram"
    )

    original_content = "# Diagrams\n\nIntroductory text about diagrams.\n\n- [Existing Diagram](./existing.d2)\n\n"
    buffers: dict[str, io.StringIO] = {
        gen_cli_module.DIAGRAM_INDEX_PATH: io.StringIO(original_content)
    }

    def fake_open(
        path: str, mode: str = "r", **_: object
    ) -> contextlib.AbstractContextManager[io.StringIO]:
        return _capture_write(buffers, path, mode)

    monkeypatch.setattr(gen_cli_module.mkdocs_gen_files, "open", fake_open)

    gen_cli_module._update_cli_index_entry(
        enabled=True
    )
    updated_content = buffers[gen_cli_module.DIAGRAM_INDEX_PATH].getvalue()

    assert (
        "Introductory text about diagrams.\n\n- [Existing Diagram](./existing.d2)\n"
        in updated_content
    )
    assert updated_content.endswith("\n\n")
    assert gen_cli_module.CLI_INDEX_ENTRY.strip() in updated_content

    gen_cli_module._update_cli_index_entry(
        enabled=False
    )
    reverted_content = buffers[gen_cli_module.DIAGRAM_INDEX_PATH].getvalue()

    assert reverted_content == original_content


def test_main_skips_diagram_when_dependency_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    gen_cli_module = importlib.import_module(
        "tools.mkdocs_suite.docs._scripts.gen_cli_diagram"
    )

    def missing_dependency_loader(*_: object, **__: object) -> None:
        message = "missing_cli_dependency"
        raise ModuleNotFoundError(message)

    monkeypatch.setattr(
        gen_cli_module, "load_cli_tooling_context", missing_dependency_loader
    )

    buffers: dict[str, io.StringIO] = {}

    def fake_open(
        path: str, mode: str = "r", **_: object
    ) -> contextlib.AbstractContextManager[io.StringIO]:
        return _capture_write(buffers, path, mode)

    monkeypatch.setattr(gen_cli_module.mkdocs_gen_files, "open", fake_open)

    caplog.set_level("WARNING", logger=gen_cli_module.LOGGER.name)

    gen_cli_module.main()

    warning_messages = " ".join(record.getMessage() for record in caplog.records)
    assert "unable to load CLI tooling context" in warning_messages

    # No diagram should be emitted when dependencies are missing; the index remains untouched.
    assert "diagrams/index.md" not in buffers
