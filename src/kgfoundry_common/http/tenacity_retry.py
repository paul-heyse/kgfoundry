"""Tenacity-based retry strategy implementation.

This module provides TenacityRetryStrategy which implements the RetryStrategy protocol using the
tenacity library for retry logic.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Callable as TypingCallable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, cast

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
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    from numpy.random import Generator

_RANDOM_SEED: ContextVar[int | None] = ContextVar("_random_seed", default=None)


@lru_cache(maxsize=1)
def _default_rng_factory() -> TypingCallable[[int | None], Generator]:
    """Return cached numpy random factory resolved lazily.

    Extended Summary
    ----------------
    This function provides a lazily-loaded factory for creating numpy.random.Generator
    instances used for jitter calculation in exponential backoff retry strategies. It
    defers numpy import until first use via gate_import to keep the module lightweight
    for hosts without numpy installed. The factory is cached with lru_cache to avoid
    repeated import overhead. This factory is consumed by _rand() to generate jitter
    values that spread retry attempts and prevent thundering herd problems.

    Returns
    -------
    TypingCallable[[int | None], Generator]
        Callable that accepts an optional seed (int | None) and returns a
        :class:`numpy.random.Generator` instance. When called with None, uses
        system random state. When called with an int seed, creates a deterministic
        generator for testing.

    Notes
    -----
    • Caching: Uses @lru_cache(maxsize=1) to ensure the factory is resolved once
      and reused across all retry attempts.
    • Lazy import: Uses gate_import() to defer numpy.random import until first
      call, keeping the module importable on minimal hosts.
    • Complexity: O(1) after first call (cached); O(1) import cost on first call.
    • Side effects: First call imports numpy.random module; subsequent calls are
      pure (no I/O, no global state mutations beyond cache).
    • Thread-safety: lru_cache is thread-safe; factory function itself is stateless.

    Examples
    --------
    >>> factory = _default_rng_factory()
    >>> rng = factory(42)  # Deterministic generator with seed
    >>> isinstance(rng.random(), float)
    True

    >>> rng2 = factory()  # System random state
    >>> 0.0 <= rng2.random() <= 1.0
    True
    """
    module = gate_import("numpy.random", "tenacity retry jitter generation")
    factory = module.default_rng
    return cast("TypingCallable[[int | None], Generator]", factory)


def _get_random_seed() -> int | None:
    """Return the configured random seed for deterministic jitter tests.

    Returns
    -------
    int | None
        Random seed value or None if not set.
    """
    return _RANDOM_SEED.get()


def _set_random_seed(seed: int | None) -> None:
    """Set the random seed used for deterministic jitter tests.

    Parameters
    ----------
    seed : int | None
        Random seed value, or None to use system random.
    """
    _RANDOM_SEED.set(seed)


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
    factory = _default_rng_factory()
    rng = factory(seed) if seed is not None else factory()
    return float(rng.random())


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
        """Predicate function to determine if exception should be retried.

        Parameters
        ----------
        e : BaseException
            Exception to evaluate for retry eligibility.

        Returns
        -------
        bool
            True if the exception should trigger a retry, False otherwise.
        """
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
    """Internal retry strategy wrapper for method-specific retry logic.

    Attributes
    ----------
    retrying : Retrying
        Configured Tenacity Retrying instance.
    """

    retrying: Retrying

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

        """
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
        """Create a configured Tenacity Retrying instance.

        Parameters
        ----------
        method : str
            HTTP method name used to determine retry policy.

        Returns
        -------
        Retrying
            Configured Tenacity Retrying instance with retry predicate,
            stop conditions, and wait strategy from the policy.
        """
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
