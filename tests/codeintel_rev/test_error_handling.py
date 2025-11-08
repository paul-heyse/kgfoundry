"""Unit tests for CodeIntel error handling infrastructure.

Tests verify exception conversion to error envelopes and decorator behavior
with various exception types and scenarios.
"""

from __future__ import annotations

import pytest
from codeintel_rev.errors import (
    FileOperationError,
    FileReadError,
    GitOperationError,
    InvalidLineRangeError,
)
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.error_handling import (
    convert_exception_to_envelope,
    handle_adapter_errors,
)

from kgfoundry_common.errors import EmbeddingError, KgFoundryError, VectorSearchError

# ==================== Exception Conversion Tests ====================


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (
            VectorSearchError("Search timeout", context={"query": "test"}),
            503,
            "vector-search-error",
        ),
        (
            EmbeddingError("Embedding generation failed", context={"model": "test"}),
            503,
            "embedding-error",
        ),
        (
            FileOperationError("File operation failed", path="test.py"),
            400,
            "file-operation-error",
        ),
        (
            FileReadError("Binary file error", path="test.png"),
            400,
            "file-operation-error",
        ),
        (
            InvalidLineRangeError("Invalid line range", path="test.py", line_range=(0, 10)),
            400,
            "invalid-parameter",
        ),
        (
            GitOperationError("Git command failed", path="test.py", git_command="blame"),
            500,
            "git-operation-error",
        ),
    ],
)
def test_kgfoundry_error_conversion(
    exception: Exception, expected_status: int, expected_code: str
) -> None:
    """Test that KgFoundryError exceptions convert correctly.

    Verifies that KgFoundryError subclasses are converted to Problem Details
    with correct HTTP status codes and error codes.
    """
    empty_result = {"value": 0}
    operation = "test:operation"

    envelope = convert_exception_to_envelope(exception, operation, empty_result)

    assert envelope["value"] == 0
    assert "error" in envelope
    assert "problem" in envelope

    problem = envelope["problem"]
    assert problem["status"] == expected_status
    assert problem["code"] == expected_code
    assert problem["type"] == f"https://kgfoundry.dev/problems/{expected_code}"
    assert problem["instance"] == operation
    # All exceptions in parametrize are KgFoundryError subclasses with message attribute
    assert isinstance(exception, KgFoundryError)
    assert problem["detail"] == exception.message


def test_file_not_found_error_conversion() -> None:
    """Test FileNotFoundError conversion to 404 error envelope."""
    exc = FileNotFoundError("File not found: test.py")
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    assert not envelope["path"]
    assert not envelope["content"]
    assert envelope["lines"] == 0
    assert envelope["size"] == 0
    assert envelope["error"] == "File not found: test.py"

    problem = envelope["problem"]
    assert problem["status"] == 404
    assert problem["code"] == "file-not-found"
    assert problem["type"] == "https://kgfoundry.dev/problems/file-not-found"
    assert problem["title"] == "File Not Found"


def test_path_outside_repository_error_conversion() -> None:
    """Test PathOutsideRepositoryError conversion to 403 error envelope."""
    exc = PathOutsideRepositoryError("Path escapes repository: ../../etc/passwd")
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assert problem["status"] == 403
    assert problem["code"] == "forbidden"
    assert problem["type"] == "https://kgfoundry.dev/problems/forbidden"
    assert problem["title"] == "Forbidden"


def test_unicode_decode_error_conversion() -> None:
    """Test UnicodeDecodeError conversion to 415 error envelope."""
    exc = UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assert problem["status"] == 415
    assert problem["code"] == "unsupported-encoding"
    assert problem["type"] == "https://kgfoundry.dev/problems/unsupported-encoding"
    assert problem["title"] == "Unsupported Encoding"
    assert "encoding" in problem.get("extensions", {})
    assert "reason" in problem.get("extensions", {})


def test_value_error_conversion() -> None:
    """Test ValueError conversion to 400 error envelope."""
    exc = ValueError("Invalid parameter: start_line must be positive")
    empty_result = {"matches": [], "total": 0}
    operation = "search:text"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assert problem["status"] == 400
    assert problem["code"] == "invalid-parameter"
    assert problem["type"] == "https://kgfoundry.dev/problems/invalid-parameter"
    assert problem["title"] == "Invalid Parameter"


def test_unknown_exception_conversion() -> None:
    """Test unknown exception conversion to 500 error envelope."""
    exc = RuntimeError("Unexpected runtime error")
    empty_result = {"value": 0}
    operation = "test:operation"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assert problem["status"] == 500
    assert problem["code"] == "internal-error"
    assert problem["type"] == "https://kgfoundry.dev/problems/internal-error"
    assert problem["title"] == "Internal Error"
    assert problem.get("extensions", {}).get("exception_type") == "RuntimeError"


def test_exception_conversion_preserves_empty_result() -> None:
    """Test that empty_result fields are preserved in error envelope."""
    exc = FileNotFoundError("File not found")
    empty_result = {
        "path": "",
        "content": "",
        "lines": 0,
        "size": 0,
        "truncated": False,
    }
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    assert not envelope["path"]
    assert not envelope["content"]
    assert envelope["lines"] == 0
    assert envelope["size"] == 0
    assert envelope["truncated"] is False
    assert "error" in envelope
    assert "problem" in envelope


def test_exception_conversion_with_context() -> None:
    """Test that exception context is included in Problem Details extensions."""
    exc = InvalidLineRangeError("Invalid line range", path="test.py", line_range=(0, 10))
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    extensions = problem.get("extensions", {})
    assert "path" in extensions
    assert extensions["path"] == "test.py"
    assert "start_line" in extensions
    assert extensions["start_line"] == 0
    assert "end_line" in extensions
    assert extensions["end_line"] == 10


# ==================== Decorator Tests ====================


def test_decorator_success_case() -> None:
    """Test decorator passes through successful results unchanged."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    def test_func() -> dict:
        return {"value": 42, "other": "data"}

    result = test_func()

    assert result["value"] == 42
    assert result["other"] == "data"
    assert "error" not in result
    assert "problem" not in result


def test_decorator_catches_exception() -> None:
    """Test decorator catches exceptions and converts to error envelope."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    def test_func() -> dict:
        msg = "File not found"
        raise FileNotFoundError(msg)

    result = test_func()

    assert result["value"] == 0
    assert "error" in result
    assert "problem" in result
    assert result["problem"]["status"] == 404


def test_decorator_preserves_function_signature() -> None:
    """Test decorator preserves function name, docstring, and annotations."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    def test_func(param: str) -> dict:
        """Test function docstring.

        Returns
        -------
        dict
            Test result dictionary.
        """
        _ = param  # Parameter used for signature testing only
        return {"value": 1}

    assert test_func.__name__ == "test_func"
    assert test_func.__doc__ is not None
    assert "Test function docstring" in test_func.__doc__
    assert "param" in test_func.__annotations__
    # Return annotation may be stored as string or type
    assert test_func.__annotations__.get("return") in {dict, "dict"}


@pytest.mark.asyncio
async def test_decorator_async_function() -> None:
    """Test decorator works with async functions."""
    import asyncio

    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    async def async_test_func() -> dict:
        await asyncio.sleep(0)  # Ensure function is actually async
        return {"value": 42}

    result = await async_test_func()

    assert result["value"] == 42
    assert "error" not in result


@pytest.mark.asyncio
async def test_decorator_async_function_error() -> None:
    """Test decorator catches exceptions in async functions."""
    import asyncio

    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    async def async_test_func() -> dict:
        await asyncio.sleep(0)  # Ensure function is actually async
        msg = "Async error"
        raise ValueError(msg)

    result = await async_test_func()

    assert result["value"] == 0
    assert "error" in result
    assert result["problem"]["status"] == 400


def test_decorator_multiple_exception_types() -> None:
    """Test decorator handles multiple exception types correctly."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    def test_func(raise_type: str) -> dict:
        if raise_type == "FileNotFoundError":
            msg = "File not found"
            raise FileNotFoundError(msg)
        if raise_type == "ValueError":
            msg = "Invalid parameter"
            raise ValueError(msg)
        if raise_type == "RuntimeError":
            msg = "Unexpected error"
            raise RuntimeError(msg)
        return {"value": 1}

    # Test FileNotFoundError
    result1 = test_func("FileNotFoundError")
    assert result1["problem"]["status"] == 404

    # Test ValueError
    result2 = test_func("ValueError")
    assert result2["problem"]["status"] == 400

    # Test RuntimeError (unknown)
    result3 = test_func("RuntimeError")
    assert result3["problem"]["status"] == 500


def test_decorator_with_kgfoundry_error() -> None:
    """Test decorator handles KgFoundryError exceptions."""
    empty_result = {"matches": [], "total": 0}

    @handle_adapter_errors(operation="search:text", empty_result=empty_result)
    def test_func() -> dict:
        msg = "Search timeout"
        raise VectorSearchError(msg, context={"query": "test"})

    result = test_func()

    assert result["matches"] == []
    assert result["total"] == 0
    assert "error" in result
    assert result["problem"]["status"] == 503
    assert result["problem"]["code"] == "vector-search-error"


def test_decorator_empty_result_variations() -> None:
    """Test decorator works with different empty_result structures."""
    # Test with open_file empty result
    open_file_empty = {"path": "", "content": "", "lines": 0, "size": 0}

    @handle_adapter_errors(operation="files:open_file", empty_result=open_file_empty)
    def open_file_func() -> dict:
        msg = "File not found"
        raise FileNotFoundError(msg)

    result1 = open_file_func()
    assert not result1["path"]
    assert not result1["content"]
    assert result1["lines"] == 0
    assert result1["size"] == 0

    # Test with list_paths empty result
    list_paths_empty = {"items": [], "total": 0, "truncated": False}

    @handle_adapter_errors(operation="files:list_paths", empty_result=list_paths_empty)
    def list_paths_func() -> dict:
        msg = "Invalid path"
        raise ValueError(msg)

    result2 = list_paths_func()
    assert result2["items"] == []
    assert result2["total"] == 0
    assert result2["truncated"] is False


# ==================== Structured Logging Tests ====================


def test_kgfoundry_error_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Test that KgFoundryError exceptions are logged with structured context."""
    import logging

    exc = VectorSearchError("Search timeout", context={"query": "test"})
    empty_result = {"matches": [], "total": 0}
    operation = "search:text"

    with caplog.at_level(logging.WARNING):
        convert_exception_to_envelope(exc, operation, empty_result)

    assert len(caplog.records) > 0
    record = caplog.records[0]
    # Structured fields are added as attributes to LogRecord via LoggerAdapter
    operation_value = getattr(record, "operation", None)
    assert operation_value == operation
    error_code_value = getattr(record, "error_code", None)
    assert error_code_value == "vector-search-error"


def test_file_not_found_error_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Test that FileNotFoundError is logged at WARNING level."""
    import logging

    exc = FileNotFoundError("File not found: test.py")
    empty_result = {"path": ""}
    operation = "files:open_file"

    with caplog.at_level(logging.WARNING):
        convert_exception_to_envelope(exc, operation, empty_result)

    assert len(caplog.records) > 0
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert "File not found" in record.message


def test_unknown_exception_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Test that unknown exceptions are logged at EXCEPTION level with stack trace."""
    import logging

    exc = RuntimeError("Unexpected error")
    empty_result = {"value": 0}
    operation = "test:operation"

    with caplog.at_level(logging.ERROR):
        convert_exception_to_envelope(exc, operation, empty_result)

    assert len(caplog.records) > 0
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    # Structured fields are added as attributes to LogRecord via LoggerAdapter
    exception_type_value = getattr(record, "exception_type", None)
    assert exception_type_value == "RuntimeError"
