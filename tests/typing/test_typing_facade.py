"""Tests for the codeintel_rev typing facade."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.typing import LoggerLike, NDArrayF32, NDArrayI64, PathLike

from tests._helpers import assertions


class _DummyLogger:
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


def test_logger_like_protocol_accepts_structural_logger() -> None:
    """LoggerLike should accept a class implementing the logging surface."""
    logger = _DummyLogger()
    assertions.expect_true(isinstance(logger, LoggerLike))
    logger.debug("message")
    assertions.expect_true(logger.last_call is not None)
    if logger.last_call is not None:
        assertions.expect_equal(logger.last_call[1], "message")


def test_pathlike_alias_includes_path(tmp_path: Path) -> None:
    """PathLike alias should accept pathlib.Path instances."""
    value: PathLike = tmp_path / "artifact"
    assertions.expect_true(isinstance(value, Path))


def test_ndarray_aliases_are_exported() -> None:
    """Ensure numpy array aliases are defined."""
    assertions.expect_true(NDArrayF32 is not None)
    assertions.expect_true(NDArrayI64 is not None)
