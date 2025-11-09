"""Tests for MkDocs serve helpers."""

from __future__ import annotations

import importlib
import importlib.util
import socket
import sys
import types
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any, cast

import pytest


@cache
def _load_serve_module() -> types.ModuleType:
    try:
        return importlib.import_module("tools.mkdocs_suite.serve")
    except ModuleNotFoundError:
        return _load_serve_module_with_stubs()


def _load_serve_module_with_stubs() -> types.ModuleType:
    tools_stub = cast("Any", sys.modules.setdefault("tools", types.ModuleType("tools")))
    if not hasattr(tools_stub, "__path__"):
        tools_stub.__path__ = []

    shared_stub = cast(
        "Any",
        sys.modules.setdefault("tools._shared", types.ModuleType("tools._shared")),
    )
    if not hasattr(shared_stub, "__path__"):
        shared_stub.__path__ = []

    if "tools._shared.logging" not in sys.modules:
        logging_stub = cast("Any", types.ModuleType("tools._shared.logging"))

        def _get_logger_stub(
            *_args: object, **_kwargs: object
        ) -> types.SimpleNamespace:
            return types.SimpleNamespace(
                info=lambda *_a, **_k: None,
                exception=lambda *_a, **_k: None,
            )

        logging_stub.get_logger = _get_logger_stub
        sys.modules["tools._shared.logging"] = logging_stub

    if "tools._shared.proc" not in sys.modules:
        proc_stub = cast("Any", types.ModuleType("tools._shared.proc"))

        class _ToolExecutionError(Exception):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args)
                self.returncode = kwargs.get("returncode")
                self.stdout = kwargs.get("stdout")
                self.stderr = kwargs.get("stderr")

        def _run_tool_stub(*_args: object, **_kwargs: object) -> object:
            message = "run_tool stubbed for tests"
            raise NotImplementedError(message)

        proc_stub.ToolExecutionError = _ToolExecutionError
        proc_stub.run_tool = _run_tool_stub
        sys.modules["tools._shared.proc"] = proc_stub

    serve_path = (
        Path(__file__).resolve().parents[2] / "tools" / "mkdocs_suite" / "serve.py"
    )
    spec = importlib.util.spec_from_file_location(
        "tests.tools.mkdocs_serve", serve_path
    )
    if spec is None or spec.loader is None:
        msg = "Unable to load tools.mkdocs_suite.serve for testing"
        raise RuntimeError(msg)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


serve = _load_serve_module()


def _iter_candidate_ports(
    host: str, family: int, start: int, count: int = 50
) -> Iterator[int]:
    for port in range(start, min(start + count, 65535) + 1):
        try:
            addrinfos = socket.getaddrinfo(
                host,
                port,
                family=family,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror:
            break

        for fam, socktype, proto, _canonname, sockaddr in addrinfos:
            with socket.socket(fam, socktype, proto) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(sockaddr)
                except OSError:
                    continue
            yield port
            break


@pytest.mark.parametrize(
    ("host", "family"),
    [("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)],
)
def test_find_available_port_prefers_unbound_port(host: str, family: int) -> None:
    if family == socket.AF_INET6 and not socket.has_ipv6:  # pragma: no cover - platform
        pytest.skip("IPv6 is not available on this platform")

    addrinfos = socket.getaddrinfo(
        host,
        0,
        family=family,
        type=socket.SOCK_STREAM,
    )
    busy: socket.socket | None = None
    for fam, socktype, proto, _canonname, sockaddr in addrinfos:
        busy = socket.socket(fam, socktype, proto)
        try:
            busy.bind(sockaddr)
        except OSError:
            busy.close()
            busy = None
            continue
        break

    if busy is None:
        pytest.skip("Unable to bind to an ephemeral port on the requested host")

    busy_port = busy.getsockname()[1]

    try:
        try:
            candidate_ports: Iterator[int] = iter(
                _iter_candidate_ports(host, family, busy_port + 1)
            )
            free_port = next(candidate_ports)
        except StopIteration:
            pytest.skip("Unable to locate a free port for the test host")

        selected = serve.find_available_port(host, busy_port, free_port)
    finally:
        busy.close()

    assert selected == free_port
