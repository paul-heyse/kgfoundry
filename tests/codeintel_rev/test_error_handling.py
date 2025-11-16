"""Unit tests for CodeIntel error handling infrastructure.

Tests verify exception conversion to error envelopes and decorator behavior
with various exception types and scenarios.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

import pytest
from codeintel_rev.errors import (
    FileOperationError,
    FileReadError,
    GitOperationError,
    InvalidLineRangeError,
    PathNotDirectoryError,
    PathNotFoundError,
)
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.error_handling import (
    convert_exception_to_envelope,
    format_error_response,
    handle_adapter_errors,
)

from kgfoundry_common.errors import EmbeddingError, KgFoundryError, VectorSearchError
from kgfoundry_common.problem_details import ProblemDetails
from tests._helpers import assertions


def test_format_error_response_path_outside_repo() -> None:
    """format_error_response maps PathOutsideRepositoryError to 400."""
    exc = PathOutsideRepositoryError("Path escapes repository")
    response = format_error_response(exc, instance="files:list_paths")

    problem = cast("ProblemDetails", response["problem"])
    assertions.expect_equal(response["status"], 400)
    code = problem.get("code")
    problem_type = problem.get("type")
    instance = problem.get("instance")
    assertions.expect_true(isinstance(code, str), reason="code should be str")
    assertions.expect_equal(code, "path-outside-repo")
    assertions.expect_true(isinstance(problem_type, str), reason="problem_type should be str")
    assertions.expect_equal(problem_type, "https://kgfoundry.dev/problems/path-outside-repo")
    assertions.expect_true(isinstance(instance, str), reason="instance should be str")
    assertions.expect_equal(instance, "files:list_paths")


def test_format_error_response_path_not_directory() -> None:
    """format_error_response maps PathNotDirectoryError to 400."""
    exc = PathNotDirectoryError("Not a directory", path="README.md")
    response = format_error_response(exc, instance="files:list_paths")

    problem = cast("ProblemDetails", response["problem"])
    assertions.expect_equal(response["status"], 400)
    code = problem.get("code")
    title = problem.get("title")
    assertions.expect_true(isinstance(code, str), reason="code should be str")
    assertions.expect_equal(code, "path-not-directory")
    assertions.expect_true(isinstance(title, str), reason="title should be str")
    assertions.expect_equal(title, "PathNotDirectoryError")


def test_format_error_response_path_not_found() -> None:
    """format_error_response maps PathNotFoundError to 404."""
    exc = PathNotFoundError("Path not found", path="missing.py")
    response = format_error_response(exc, instance="files:open_file")

    problem = cast("ProblemDetails", response["problem"])
    assertions.expect_equal(response["status"], 404)
    code = problem.get("code")
    assertions.expect_true(isinstance(code, str), reason="code should be str")
    assertions.expect_equal(code, "path-not-found")


def test_format_error_response_not_implemented() -> None:
    """format_error_response maps NotImplementedError to 501 Problem Details."""
    exc = NotImplementedError("Operation not implemented")
    response = format_error_response(exc, instance="feature:todo")

    problem = cast("ProblemDetails", response["problem"])
    assertions.expect_equal(response["status"], 501)
    code = problem.get("code")
    status = problem.get("status")
    title = problem.get("title")
    assertions.expect_true(isinstance(code, str), reason="code should be str")
    assertions.expect_equal(code, "not-implemented")
    assertions.expect_true(isinstance(status, int), reason="status should be int")
    assertions.expect_equal(status, 501)
    assertions.expect_true(isinstance(title, str), reason="title should be str")
    assertions.expect_equal(title, "Not Implemented")


def test_format_error_response_unknown_exception() -> None:
    """format_error_response falls back to internal-error for unknown exceptions."""
    exc = RuntimeError("Unexpected failure")
    response = format_error_response(exc, instance="test:operation")

    problem = cast("ProblemDetails", response["problem"])
    assertions.expect_equal(response["status"], 500)
    code = problem.get("code")
    extensions = problem.get("extensions")
    assertions.expect_true(isinstance(code, str), reason="code should be str")
    assertions.expect_equal(code, "internal-error")
    assertions.expect_true(isinstance(extensions, dict), reason="extensions should be dict")
    if extensions is not None:
        assertions.expect_equal(extensions.get("exception_type"), "RuntimeError")


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

    assertions.expect_equal(envelope["value"], 0)
    assertions.expect_in("error", envelope)
    assertions.expect_in("problem", envelope)

    problem = envelope["problem"]
    assertions.expect_equal(problem["status"], expected_status)
    assertions.expect_equal(problem["code"], expected_code)
    assertions.expect_equal(problem["type"], f"https://kgfoundry.dev/problems/{expected_code}")
    assertions.expect_equal(problem["instance"], operation)
    # All exceptions in parametrize are KgFoundryError subclasses with message attribute
    assertions.expect_true(
        isinstance(exception, KgFoundryError), reason="exception should be KgFoundryError"
    )
    if isinstance(exception, KgFoundryError):
        assertions.expect_equal(problem["detail"], exception.message)


def test_file_not_found_error_conversion() -> None:
    """Test FileNotFoundError conversion to 404 error envelope."""
    exc = FileNotFoundError("File not found: test.py")
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    assertions.expect_false(bool(envelope["path"]), reason="path should be empty")
    assertions.expect_false(bool(envelope["content"]), reason="content should be empty")
    assertions.expect_equal(envelope["lines"], 0)
    assertions.expect_equal(envelope["size"], 0)
    assertions.expect_equal(envelope["error"], "File not found: test.py")

    problem = envelope["problem"]
    assertions.expect_equal(problem["status"], 404)
    assertions.expect_equal(problem["code"], "path-not-found")
    assertions.expect_equal(problem["type"], "https://kgfoundry.dev/problems/path-not-found")
    assertions.expect_equal(problem["title"], "Path Not Found")


def test_path_outside_repository_error_conversion() -> None:
    """Test PathOutsideRepositoryError conversion to 403 error envelope."""
    exc = PathOutsideRepositoryError("Path escapes repository: ../../etc/passwd")
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assertions.expect_equal(problem["status"], 400)
    assertions.expect_equal(problem["code"], "path-outside-repo")
    assertions.expect_equal(problem["type"], "https://kgfoundry.dev/problems/path-outside-repo")
    assertions.expect_equal(problem["title"], "Path Outside Repository")


def test_unicode_decode_error_conversion() -> None:
    """Test UnicodeDecodeError conversion to 415 error envelope."""
    exc = UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assertions.expect_equal(problem["status"], 415)
    assertions.expect_equal(problem["code"], "unsupported-encoding")
    assertions.expect_equal(problem["type"], "https://kgfoundry.dev/problems/unsupported-encoding")
    assertions.expect_equal(problem["title"], "Unsupported Encoding")
    assertions.expect_in("encoding", problem.get("extensions", {}))
    assertions.expect_in("reason", problem.get("extensions", {}))


def test_value_error_conversion() -> None:
    """Test ValueError conversion to 400 error envelope."""
    exc = ValueError("Invalid parameter: start_line must be positive")
    empty_result = {"matches": [], "total": 0}
    operation = "search:text"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assertions.expect_equal(problem["status"], 400)
    assertions.expect_equal(problem["code"], "invalid-parameter")
    assertions.expect_equal(problem["type"], "https://kgfoundry.dev/problems/invalid-parameter")
    assertions.expect_equal(problem["title"], "Invalid Parameter")


def test_unknown_exception_conversion() -> None:
    """Test unknown exception conversion to 500 error envelope."""
    exc = RuntimeError("Unexpected runtime error")
    empty_result = {"value": 0}
    operation = "test:operation"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    assertions.expect_equal(problem["status"], 500)
    assertions.expect_equal(problem["code"], "internal-error")
    assertions.expect_equal(problem["type"], "https://kgfoundry.dev/problems/internal-error")
    assertions.expect_equal(problem["title"], "Internal Error")
    assertions.expect_equal(problem.get("extensions", {}).get("exception_type"), "RuntimeError")


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

    assertions.expect_false(bool(envelope["path"]), reason="path should be empty")
    assertions.expect_false(bool(envelope["content"]), reason="content should be empty")
    assertions.expect_equal(envelope["lines"], 0)
    assertions.expect_equal(envelope["size"], 0)
    assertions.expect_false(envelope["truncated"], reason="truncated should be False")
    assertions.expect_in("error", envelope)
    assertions.expect_in("problem", envelope)


def test_exception_conversion_with_context() -> None:
    """Test that exception context is included in Problem Details extensions."""
    exc = InvalidLineRangeError("Invalid line range", path="test.py", line_range=(0, 10))
    empty_result = {"path": "", "content": "", "lines": 0, "size": 0}
    operation = "files:open_file"

    envelope = convert_exception_to_envelope(exc, operation, empty_result)

    problem = envelope["problem"]
    extensions = problem.get("extensions", {})
    assertions.expect_in("path", extensions)
    assertions.expect_equal(extensions["path"], "test.py")
    assertions.expect_in("start_line", extensions)
    assertions.expect_equal(extensions["start_line"], 0)
    assertions.expect_in("end_line", extensions)
    assertions.expect_equal(extensions["end_line"], 10)


# ==================== Decorator Tests ====================


def test_decorator_success_case() -> None:
    """Test decorator passes through successful results unchanged."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    def test_func() -> dict:
        return {"value": 42, "other": "data"}

    result = test_func()

    assertions.expect_equal(result["value"], 42)
    assertions.expect_equal(result["other"], "data")
    assertions.expect_false("error" in result, reason="should not have error")
    assertions.expect_false("problem" in result, reason="should not have problem")


def test_decorator_catches_exception() -> None:
    """Test decorator catches exceptions and converts to error envelope."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    def test_func() -> dict:
        msg = "File not found"
        raise FileNotFoundError(msg)

    result = test_func()

    assertions.expect_equal(result["value"], 0)
    assertions.expect_in("error", result)
    assertions.expect_in("problem", result)
    assertions.expect_equal(result["problem"]["status"], 404)


def test_decorator_preserves_function_signature() -> None:
    """Test decorator preserves function name, docstring, and annotations."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    def test_func(param: str) -> dict:
        """Test function docstring.

        Parameters
        ----------
        param : str
            Test parameter used for signature testing only.

        Returns
        -------
        dict
            Test result dictionary.
        """
        _ = param  # Parameter used for signature testing only
        return {"value": 1}

    assertions.expect_equal(test_func.__name__, "test_func")
    assertions.expect_true(test_func.__doc__ is not None, reason="docstring should exist")
    if test_func.__doc__ is not None:
        assertions.expect_in("Test function docstring", test_func.__doc__)
    assertions.expect_in("param", test_func.__annotations__)
    # Return annotation may be stored as string or type
    return_annotation = test_func.__annotations__.get("return")
    if return_annotation is not None:
        assertions.expect_in(return_annotation, {dict, "dict"})


@pytest.mark.asyncio
async def test_decorator_async_function() -> None:
    """Test decorator works with async functions."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    async def async_test_func() -> dict:
        await asyncio.sleep(0)  # Ensure function is actually async
        return {"value": 42}

    result = await async_test_func()

    assertions.expect_equal(result["value"], 42)
    assertions.expect_false("error" in result, reason="should not have error")


@pytest.mark.asyncio
async def test_decorator_async_function_error() -> None:
    """Test decorator catches exceptions in async functions."""
    empty_result = {"value": 0}

    @handle_adapter_errors(operation="test:operation", empty_result=empty_result)
    async def async_test_func() -> dict:
        await asyncio.sleep(0)  # Ensure function is actually async
        msg = "Async error"
        raise ValueError(msg)

    result = await async_test_func()

    assertions.expect_equal(result["value"], 0)
    assertions.expect_in("error", result)
    assertions.expect_equal(result["problem"]["status"], 400)


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
    assertions.expect_equal(result1["problem"]["status"], 404)

    # Test ValueError
    result2 = test_func("ValueError")
    assertions.expect_equal(result2["problem"]["status"], 400)

    # Test RuntimeError (unknown)
    result3 = test_func("RuntimeError")
    assertions.expect_equal(result3["problem"]["status"], 500)


def test_decorator_with_kgfoundry_error() -> None:
    """Test decorator handles KgFoundryError exceptions."""
    empty_result = {"matches": [], "total": 0}

    @handle_adapter_errors(operation="search:text", empty_result=empty_result)
    def test_func() -> dict:
        msg = "Search timeout"
        raise VectorSearchError(msg, context={"query": "test"})

    result = test_func()

    assertions.expect_equal(result["matches"], [])
    assertions.expect_equal(result["total"], 0)
    assertions.expect_in("error", result)
    assertions.expect_equal(result["problem"]["status"], 503)
    assertions.expect_equal(result["problem"]["code"], "vector-search-error")


def test_decorator_empty_result_variations() -> None:
    """Test decorator works with different empty_result structures."""
    # Test with open_file empty result
    open_file_empty = {"path": "", "content": "", "lines": 0, "size": 0}

    @handle_adapter_errors(operation="files:open_file", empty_result=open_file_empty)
    def open_file_func() -> dict:
        msg = "File not found"
        raise FileNotFoundError(msg)

    result1 = open_file_func()
    assertions.expect_false(bool(result1["path"]), reason="path should be empty")
    assertions.expect_false(bool(result1["content"]), reason="content should be empty")
    assertions.expect_equal(result1["lines"], 0)
    assertions.expect_equal(result1["size"], 0)

    # Test with list_paths empty result
    list_paths_empty = {"items": [], "total": 0, "truncated": False}

    @handle_adapter_errors(operation="files:list_paths", empty_result=list_paths_empty)
    def list_paths_func() -> dict:
        msg = "Invalid path"
        raise ValueError(msg)

    result2 = list_paths_func()
    assertions.expect_equal(result2["items"], [])
    assertions.expect_equal(result2["total"], 0)
    assertions.expect_false(result2["truncated"], reason="truncated should be False")


# ==================== Structured Logging Tests ====================


def test_kgfoundry_error_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Test that KgFoundryError exceptions are logged with structured context."""
    exc = VectorSearchError("Search timeout", context={"query": "test"})
    empty_result = {"matches": [], "total": 0}
    operation = "search:text"

    with caplog.at_level(logging.WARNING):
        convert_exception_to_envelope(exc, operation, empty_result)

    assertions.expect_true(len(caplog.records) > 0, reason="should have log records")
    record = caplog.records[0]
    # Structured fields are added as attributes to LogRecord via LoggerAdapter
    operation_value = getattr(record, "operation", None)
    assertions.expect_equal(operation_value, operation)
    error_code_value = getattr(record, "error_code", None)
    assertions.expect_equal(error_code_value, "vector-search-error")


def test_file_not_found_error_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Test that FileNotFoundError is logged at WARNING level."""
    exc = FileNotFoundError("File not found: test.py")
    empty_result = {"path": ""}
    operation = "files:open_file"

    with caplog.at_level(logging.WARNING):
        convert_exception_to_envelope(exc, operation, empty_result)

    assertions.expect_true(len(caplog.records) > 0, reason="should have log records")
    record = caplog.records[0]
    assertions.expect_equal(record.levelno, logging.WARNING)
    assertions.expect_in("not found", record.message.lower())


def test_unknown_exception_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Test that unknown exceptions are logged at EXCEPTION level with stack trace."""
    exc = RuntimeError("Unexpected error")
    empty_result = {"value": 0}
    operation = "test:operation"

    with caplog.at_level(logging.ERROR):
        convert_exception_to_envelope(exc, operation, empty_result)

    assertions.expect_true(len(caplog.records) > 0, reason="should have log records")
    record = caplog.records[0]
    assertions.expect_equal(record.levelno, logging.ERROR)
    # Structured fields are added as attributes to LogRecord via LoggerAdapter
    exception_type_value = getattr(record, "exception_type", None)
    assertions.expect_equal(exception_type_value, "RuntimeError")
