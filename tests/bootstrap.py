"""Testing bootstrap helpers for kgfoundry.

This module centralises environment setup so pytest (and any other test
runner) can resolve the project package layout without ad-hoc hacks. It is
imported by ``tests.conftest`` before any of the test modules, ensuring the
``src`` directory is always on ``sys.path`` and optional dependencies can be
loaded lazily.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast, no_type_check

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from click.testing import Result

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SRC_PATH: Final[Path] = REPO_ROOT / "src"


class _BootstrapState:
    bootstrapped: bool = False


@no_type_check
def _load_cli_runner_cls() -> type[_CliRunnerProtocol] | None:
    try:
        testing_module = import_module("typer.testing")
    except ImportError:  # pragma: no cover - typer not installed
        return None

    candidate_obj: object | None = getattr(testing_module, "CliRunner", None)
    if candidate_obj is None or not isinstance(candidate_obj, type):
        return None
    runner_cls_obj = cast("type[_CliRunnerProtocol]", candidate_obj)
    if not hasattr(runner_cls_obj, "invoke"):
        return None
    return runner_cls_obj


def ensure_src_path() -> None:
    """Add the ``src`` directory to ``sys.path`` exactly once."""
    if _BootstrapState.bootstrapped:
        return
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))
        importlib.invalidate_caches()
    _BootstrapState.bootstrapped = True


def load_optional_module(module_name: str) -> ModuleType | None:
    """Return ``module_name`` when importable, otherwise ``None``.

    Parameters
    ----------
    module_name : str
        Module name to import.

    Returns
    -------
    ModuleType | None
        Imported module if available, otherwise None.
    """
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return None
    return importlib.import_module(module_name)


def load_optional_attr(module_name: str, attr_name: str) -> object | None:
    """Return ``getattr`` from ``module_name`` when available.

    ``None`` is returned when either the module or the attribute cannot be
    imported. Consumers remain responsible for type-casting the result.

    Parameters
    ----------
    module_name : str
        Module name to import from.
    attr_name : str
        Attribute name to retrieve.

    Returns
    -------
    object | None
        Attribute value if available, otherwise None.
    """
    module = load_optional_module(module_name)
    if module is None:
        return None
    return cast("object | None", getattr(module, attr_name, None))


# Ensure the src layout is active as soon as the bootstrap module is imported.
ensure_src_path()

# Default test environment configuration: synthetic data + stubbed heavy deps.
os.environ.setdefault("KGFOUNDRY_TEST_USE_REAL_DATA", "0")
os.environ.setdefault("KGFOUNDRY_TEST_MODE", "1")
os.environ.setdefault("KGFOUNDRY_TEST_VLLM_STUB", "1")


class _CliRunnerProtocol(Protocol):
    def invoke(self, *args: object, **kwargs: object) -> Result:
        """Invoke the CLI with the provided arguments."""
        ...


@no_type_check
def _patch_cli_runner_mix_stderr() -> None:
    """Allow ``CliRunner.invoke`` to accept ``mix_stderr`` across Click versions."""
    cli_runner_cls = _load_cli_runner_cls()
    if cli_runner_cls is None:
        return

    if hasattr(cli_runner_cls.invoke, "__kgfoundry_mixstderr__"):
        return

    signature = inspect.signature(cli_runner_cls.invoke)
    if "mix_stderr" in signature.parameters:
        return

    invoke_attr = cast("object", cli_runner_cls.invoke)
    invoke_callable = cast("Callable[..., Result]", invoke_attr)

    def invoke(self: object, *invoke_args: object, **invoke_kwargs: object) -> Result:
        """Invoke CLI command with mix_stderr parameter removed.

        Parameters
        ----------
        self : object
            CLI runner instance.
        *invoke_args : object
            Positional arguments.
        **invoke_kwargs : object
            Keyword arguments (mix_stderr removed if present).

        Returns
        -------
        Result
            CLI execution result.
        """
        invoke_kwargs.pop("mix_stderr", None)
        return invoke_callable(self, *invoke_args, **invoke_kwargs)

    invoke.__kgfoundry_mixstderr__ = True
    cli_runner_cls.invoke = cast("Callable[..., Result]", invoke)


_patch_cli_runner_mix_stderr()
