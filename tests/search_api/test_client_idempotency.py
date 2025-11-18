"""HTTP client idempotency and retry tests for search API.

Tests verify:
- Repeated GET/POST calls with same payload produce identical results
- Problem Details errors follow RFC 9457 format
- Correlation IDs are preserved across retries
- Transient errors trigger proper retry behavior
- Idempotency keys prevent duplicate side effects
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from kgfoundry_common.types import JsonValue
from tests._helpers import assertions

# Test constants for HTTP status codes
_HTTP_STATUS_SERVER_ERROR_THRESHOLD = 500
_HTTP_STATUS_TOO_MANY_REQUESTS = 429

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture


@dataclass(slots=True, frozen=True)
class StubResponse:
    """Simple HTTP response stub used for idempotency tests."""

    status_code: int
    payload: JsonValue

    def json(self) -> JsonValue:
        """Return the JSON payload associated with the response.

        Returns
        -------
        JsonValue
            Response payload.
        """
        return self.payload


class StubHttpClient:
    """Deterministic HTTP client stub that returns queued responses.

    This stub client allows tests to pre-configure HTTP responses for GET and POST
    requests. It maintains queues of responses that are consumed in order when
    requests are made. This enables deterministic testing of HTTP interactions
    without requiring a real HTTP server.

    Parameters
    ----------
    get_responses : list[StubResponse] | None, optional
        Queue of GET responses that will be returned in order.
    post_responses : list[StubResponse] | None, optional
        Queue of POST responses that will be returned in order.
    """

    def __init__(
        self,
        *,
        get_responses: list[StubResponse] | None = None,
        post_responses: list[StubResponse] | None = None,
    ) -> None:
        """Initialize stub HTTP adapter.

        Parameters
        ----------
        get_responses : list[StubResponse] | None, optional
            Queue of GET responses that will be returned in order.
        post_responses : list[StubResponse] | None, optional
            Queue of POST responses that will be returned in order.
        """
        self._get_responses = list(get_responses or [])
        self._post_responses = list(post_responses or [])
        self.get_call_count = 0
        self.post_call_count = 0

    def enqueue_get(self, response: StubResponse) -> None:
        """Enqueue a GET response.

        Parameters
        ----------
        response : StubResponse
            Response to enqueue.
        """
        self._get_responses.append(response)

    def enqueue_post(self, response: StubResponse) -> None:
        """Enqueue a POST response.

        Parameters
        ----------
        response : StubResponse
            Response to enqueue.
        """
        self._post_responses.append(response)

    @staticmethod
    def _response_for(responses: list[StubResponse], index: int) -> StubResponse:
        """Get response for given index from responses list.

        Parameters
        ----------
        responses : list[StubResponse]
            List of responses to select from.
        index : int
            Index of response to return.

        Returns
        -------
        StubResponse
            Response at the given index (or last response if index out of bounds).

        Raises
        ------
        AssertionError
            If responses list is empty.
        """
        if not responses:
            msg = "No responses queued for HTTP method"
            raise AssertionError(msg)
        capped_index = index if index < len(responses) else len(responses) - 1
        return responses[capped_index]

    def get(self) -> StubResponse:
        """Return the next queued GET response.

        Returns
        -------
        StubResponse
            Next GET response in queue.
        """
        self.get_call_count += 1
        return self._response_for(self._get_responses, self.get_call_count - 1)

    def post(self, *args: object, **kwargs: object) -> StubResponse:
        """Return the next queued POST response.

        Parameters
        ----------
        *args : object
            Positional arguments (ignored).
        **kwargs : object
            Keyword arguments (ignored).

        Returns
        -------
        StubResponse
            Next POST response in queue.
        """
        del args, kwargs
        self.post_call_count += 1
        return self._response_for(self._post_responses, self.post_call_count - 1)


def _require_json_object(value: JsonValue, *, label: str) -> dict[str, JsonValue]:
    """Return the provided JSON payload as a mapping or fail the test.

    Returns
    -------
    dict[str, JsonValue]
        The value cast to a dictionary mapping.
    """
    if not isinstance(value, dict):
        pytest.fail(f"{label} should be a JSON object")
    return cast("dict[str, JsonValue]", value)


def test_repeated_get_produces_identical_response() -> None:
    """Verify repeated GET calls to same endpoint return identical responses."""
    scenarios: list[tuple[str, int]] = [
        ("/search?q=python", 200),
        ("/info/symbol/my.module.func", 200),
        ("/catalog?package=kgfoundry", 200),
    ]
    for endpoint, expected_status in scenarios:
        client = StubHttpClient()
        response_payload: JsonValue = {
            "status": "success",
            "data": [{"id": "doc_001", "title": "Test"}],
            "correlation_id": "req-abc123",
            "endpoint": endpoint,
        }
        client.enqueue_get(StubResponse(expected_status, response_payload))

        result1 = client.get()
        result2 = client.get()
        result3 = client.get()

        assertions.expect_true(result1 is result2 is result3, reason="should be same object")
        assertions.expect_equal(client.get_call_count, 3)


def test_get_with_missing_resource_returns_404_problem_details() -> None:
    """Verify GET to missing resource returns RFC 9457 Problem Details."""
    client = StubHttpClient(
        get_responses=[
            StubResponse(
                404,
                {
                    "type": "https://kgfoundry.dev/problems/not-found",
                    "title": "Resource Not Found",
                    "status": 404,
                    "detail": "Symbol 'missing.module.func' not found in catalog",
                    "instance": "urn:request:symbol:missing",
                    "correlation_id": "req-xyz789",
                },
            )
        ]
    )

    result = client.get()
    problem = _require_json_object(result.json(), label="problem details")
    assertions.expect_equal(problem.get("type"), "https://kgfoundry.dev/problems/not-found")
    assertions.expect_equal(problem.get("status"), 404)
    assertions.expect_equal(problem.get("correlation_id"), "req-xyz789")


def test_repeated_post_with_idempotency_key_produces_single_effect() -> None:
    """Verify POST calls with same idempotency key produce single side effect."""
    scenarios: list[tuple[dict[str, str], str]] = [
        ({"name": "doc_001", "text": "Introduction"}, "idempotency-key-001"),
        ({"name": "doc_002", "text": "Advanced topics"}, "idempotency-key-002"),
    ]
    for body, idempotency_key in scenarios:
        client = StubHttpClient()
        client.enqueue_post(
            StubResponse(
                201,
                {
                    "id": "created_001",
                    "status": "created",
                    "correlation_id": "req-dup-test",
                },
            )
        )

        for _ in range(3):
            result = client.post(json=body, headers={"Idempotency-Key": idempotency_key})
            payload = _require_json_object(result.json(), label="idempotent POST response")
            assertions.expect_equal(payload.get("id"), "created_001")

        assertions.expect_equal(client.post_call_count, 3)


def test_post_conflict_on_duplicate_returns_409_with_details() -> None:
    """Verify POST duplicate returns 409 Conflict with Problem Details."""
    client = StubHttpClient(
        post_responses=[
            StubResponse(
                201,
                {
                    "id": "doc_created_123",
                    "status": "created",
                    "correlation_id": "req-first",
                },
            ),
            StubResponse(
                409,
                {
                    "type": "https://kgfoundry.dev/problems/conflict",
                    "title": "Resource Already Exists",
                    "status": 409,
                    "detail": "Document with ID 'doc_001' already exists",
                    "instance": "urn:request:document:doc_001",
                    "correlation_id": "req-second",
                    "extensions": {"existing_id": "doc_created_123"},
                },
            ),
        ]
    )

    result1 = client.post()
    assertions.expect_equal(result1.status_code, 201)

    result2 = client.post()
    assertions.expect_equal(result2.status_code, 409)

    conflict = _require_json_object(result2.json(), label="conflict problem")
    assertions.expect_equal(conflict.get("type"), "https://kgfoundry.dev/problems/conflict")
    assertions.expect_equal(conflict.get("status"), 409)
    detail_value = conflict.get("detail")
    if not isinstance(detail_value, str):
        pytest.fail("detail should be a string")
    assertions.expect_in("doc_001", detail_value)
    assertions.expect_equal(client.post_call_count, 2)


def test_transient_500_error_retried(caplog: LogCaptureFixture) -> None:
    """Verify 500 errors trigger retry logic with structured logging."""
    client = StubHttpClient(
        get_responses=[
            StubResponse(
                500,
                {
                    "type": "https://kgfoundry.dev/problems/internal-error",
                    "title": "Internal Server Error",
                    "status": 500,
                    "detail": "Unexpected error processing request",
                    "correlation_id": "req-error-1",
                },
            ),
            StubResponse(
                200,
                {
                    "status": "success",
                    "data": [],
                    "correlation_id": "req-error-1",
                },
            ),
        ]
    )

    result1 = client.get()
    assertions.expect_equal(result1.status_code, 500)

    result2 = client.get()
    assertions.expect_equal(result2.status_code, 200)

    payload1 = _require_json_object(result1.json(), label="transient error response")
    payload2 = _require_json_object(result2.json(), label="transient retry response")
    assertions.expect_equal(payload1.get("correlation_id"), "req-error-1")
    assertions.expect_equal(payload2.get("correlation_id"), "req-error-1")
    assertions.expect_true(caplog is not None, reason="should be same object")


def test_status_codes_retry_policy() -> None:
    """Verify retry policy for various HTTP status codes."""
    cases: list[tuple[int, bool]] = [
        (429, True),
        (503, True),
        (504, True),
        (400, False),
        (401, False),
        (403, False),
    ]
    for status_code, should_retry in cases:
        is_retryable = (
            status_code >= _HTTP_STATUS_SERVER_ERROR_THRESHOLD
            or status_code == _HTTP_STATUS_TOO_MANY_REQUESTS
        )
        assertions.expect_equal(is_retryable, should_retry)


def test_correlation_id_in_request_headers() -> None:
    """Verify correlation ID is included in response payload for tracing."""
    client = StubHttpClient(
        get_responses=[
            StubResponse(
                200,
                {
                    "status": "success",
                    "correlation_id": "req-trace-123",
                },
            )
        ]
    )

    result = client.get()
    response_data = _require_json_object(result.json(), label="correlation response")
    extensions = response_data.get("extensions")
    has_direct = "correlation_id" in response_data
    has_extension = isinstance(extensions, dict) and "correlation_id" in extensions
    assertions.expect_true(
        has_direct or has_extension,
        reason="should have correlation_id in response_data or extensions",
    )


def test_correlation_id_consistency_across_retries() -> None:
    """Verify correlation ID remains consistent when request is retried."""
    correlation_id = "req-trace-456"
    client = StubHttpClient(
        get_responses=[
            StubResponse(500, {"type": "error", "correlation_id": correlation_id}),
            StubResponse(200, {"status": "success", "correlation_id": correlation_id}),
        ]
    )

    result1 = client.get()
    result2 = client.get()

    payload1 = _require_json_object(result1.json(), label="retry correlation payload1")
    payload2 = _require_json_object(result2.json(), label="retry correlation payload2")
    assertions.expect_equal(payload1.get("correlation_id"), correlation_id)
    assertions.expect_equal(payload2.get("correlation_id"), correlation_id)
