"""Tenacity-based retry strategy implementation.

This module provides TenacityRetryStrategy which implements the RetryStrategy protocol using the
tenacity library for retry logic.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
)
from tenacity.wait import wait_base

from kgfoundry_common.http.errors import HttpStatusError
from kgfoundry_common.http.policy import RetryPolicyDoc
from kgfoundry_common.http.types import RetryStrategy


def _get_random_seed() -> int | None:
    """Get random seed using function attribute pattern.

    Returns
    -------
    int | None
        Random seed value or None if not set.
    """
    return getattr(_get_random_seed, "_seed", None)  # Function attribute pattern


def _set_random_seed(seed: int | None) -> None:
    """Set random seed for testing.

    Parameters
    ----------
    seed : int | None
        Random seed value, or None to use system random.
    """
    _get_random_seed._seed = seed  # type: ignore[attr-defined]  # noqa: SLF001  # Function attribute pattern


@dataclass(frozen=True)
class WaitRetryAfterOrJitter(wait_base):
    """Wait strategy that respects Retry-After headers or uses exponential backoff with jitter.

    Attributes
    ----------
    initial : float
        Initial wait time in seconds.
    max_s : float
        Maximum wait time in seconds.
    jitter : float
        Jitter fraction (0.0 to 1.0).
    base : float
        Base multiplier for exponential backoff.
    respect_retry_after : bool
        Whether to respect Retry-After headers.
    """

    initial: float
    max_s: float
    jitter: float  # 0..1 fraction
    base: float
    respect_retry_after: bool

    def __call__(self, retry_state: object) -> float:
        """Calculate wait time for retry.

        Parameters
        ----------
        retry_state : object
            Tenacity retry state object.

        Returns
        -------
        float
            Wait time in seconds.
        """
        # attempt starts at 1
        attempt = getattr(retry_state, "attempt_number", 1)
        # If last exception had Retry-After, prefer it:
        sleep = None
        if self.respect_retry_after:
            outcome = getattr(retry_state, "outcome", None)
            exc = outcome.exception() if outcome else None
            if isinstance(exc, HttpStatusError):
                ra = _parse_retry_after(exc.headers.get("Retry-After"))
                if ra is not None:
                    sleep = min(ra, self.max_s)
        if sleep is None:
            # Exponential backoff with jitter
            base = min(self.max_s, self.initial * (self.base ** (attempt - 1)))
            jitter_amount = base * self.jitter
            sleep = max(0.0, base - jitter_amount + _rand() * (2 * jitter_amount))
        return sleep


def _parse_retry_after(s: str | None) -> float | None:
    """Parse Retry-After header value.

    Parameters
    ----------
    s : str | None
        Retry-After header value.

    Returns
    -------
    float | None
        Seconds to wait, or None if invalid.
    """
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _rand() -> float:
    """Generate random float for jitter calculation.

    Returns
    -------
    float
        Random float between 0.0 and 1.0.

    Notes
    -----
    This uses standard random for jitter, not cryptographic randomness.
    Jitter does not require cryptographic security - it's only for spreading
    retry attempts to avoid thundering herd problems.
    """
    seed = _get_random_seed()
    if seed is not None:
        # Use seeded random for deterministic testing
        rng = random.Random(seed)  # noqa: S311  # Jitter doesn't need cryptographic randomness
        return rng.random()
    # Use module-level random for jitter (non-cryptographic use case)
    return random.random()  # noqa: S311  # Jitter doesn't need cryptographic randomness


def _status_in_sets(status: int, sets: tuple[tuple[int, int] | int, ...]) -> bool:
    """Check if status code matches any in the sets.

    Parameters
    ----------
    status : int
        HTTP status code.
    sets : tuple[tuple[int, int] | int, ...]
        Status codes or ranges to check.

    Returns
    -------
    bool
        True if status matches any entry in sets.
    """
    for x in sets:
        if isinstance(x, int) and status == x:
            return True
        if isinstance(x, tuple) and x[0] <= status <= x[1]:
            return True
    return False


def _should_retry_exception(method: str, policy: RetryPolicyDoc) -> Callable[[BaseException], bool]:
    """Create predicate function for retry decision based on exception.

    Parameters
    ----------
    method : str
        HTTP method name.
    policy : RetryPolicyDoc
        Retry policy configuration.

    Returns
    -------
    Callable[[BaseException], bool]
        Predicate function that returns True if exception should be retried.
    """
    allowed_methods = set(policy.methods)
    retry_exc_names = set(policy.retry_exceptions)
    give_up = set(policy.give_up_status)
    status_sets = policy.retry_status

    def _pred(e: BaseException) -> bool:
        if method.upper() not in allowed_methods:
            return False
        # idempotency guard for non-idempotent methods
        if policy.require_idempotency_key and method.upper() not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            # Tenacity has no access to headers; enforce earlier in client (see below)
            return False
        # Exception-based rule
        name = e.__class__.__name__
        if name in retry_exc_names:
            return True
        # HTTP status-based rule
        if isinstance(e, HttpStatusError):
            if e.status in give_up:
                return False
            return _status_in_sets(e.status, status_sets)
        return False

    return _pred


@dataclass(frozen=True)
class _MethodStrategy(RetryStrategy[object]):
    retrying: Retrying

    def run(self, fn: Callable[[], object]) -> object:
        return self.retrying(fn)


class TenacityRetryStrategy(RetryStrategy[object]):
    """Retry strategy implementation using tenacity library.

    Parameters
    ----------
    policy : RetryPolicyDoc
        Retry policy configuration.
    """

    def __init__(self, policy: RetryPolicyDoc) -> None:
        self.policy = policy

    def run(self, fn: Callable[[], object]) -> object:
        """Execute function with retry logic.

        Parameters
        ----------
        fn : Callable[[], object]
            Function to execute with retries.

        Returns
        -------
        object
            Result of function execution.

        Notes
        -----
        This method may raise any exception that the retried function raises.
        The tenacity Retrying instance will re-raise the final exception after
        all retries are exhausted. The actual exception type depends on the
        function being retried, so we cannot document a specific exception type
        in the Raises section. This is a known limitation of static analysis
        when dealing with third-party retry libraries that propagate exceptions
        from user-provided functions.
        """
        strategy = _MethodStrategy(self._build_retrying("*UNKNOWN*"))
        return strategy.run(fn)

    def for_method(self, method: str) -> RetryStrategy[object]:
        """Create method-specific retry strategy.

        Parameters
        ----------
        method : str
            HTTP method name.

        Returns
        -------
        RetryStrategy[object]
            New retry strategy instance for the method.
        """
        return _MethodStrategy(self._build_retrying(method))

    def _build_retrying(self, method: str) -> Retrying:
        """Create a configured Tenacity Retrying instance."""
        predicate = retry_if_exception(_should_retry_exception(method=method, policy=self.policy))
        stopper = stop_after_attempt(self.policy.stop_after_attempt)
        if self.policy.stop_after_delay_s:
            stopper |= stop_after_delay(self.policy.stop_after_delay_s)
        waiter = WaitRetryAfterOrJitter(
            initial=self.policy.wait_initial_s,
            max_s=self.policy.wait_max_s,
            jitter=self.policy.wait_jitter,
            base=self.policy.wait_base,
            respect_retry_after=self.policy.respect_retry_after,
        )
        return Retrying(retry=predicate, stop=stopper, wait=waiter, reraise=True)
