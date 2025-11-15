"""Retry policy configuration and loading.

This module provides RetryPolicyDoc dataclass and PolicyRegistry for loading and managing retry
policies from YAML files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml


@dataclass(frozen=True)
class RetryPolicyDoc:
    """Retry policy configuration document.

    Attributes
    ----------
    name : str
        Policy name identifier.
    description : str | None
        Human-readable description of the policy.
    methods : tuple[str, ...]
        HTTP methods this policy applies to.
    retry_status : tuple[tuple[int, int] | int, ...]
        HTTP status codes to retry on (can be ranges like (500, 504) or single codes).
    retry_exceptions : tuple[str, ...]
        Exception class names to retry on.
    give_up_status : tuple[int, ...]
        HTTP status codes that should not be retried.
    respect_retry_after : bool
        Whether to respect Retry-After headers.
    require_idempotency_key : bool
        Whether idempotency key is required for non-idempotent methods.
    stop_after_attempt : int
        Maximum number of retry attempts.
    stop_after_delay_s : float | None
        Maximum total delay in seconds before giving up.
    wait_kind : str
        Type of wait strategy (e.g., "exponential").
    wait_initial_s : float
        Initial wait time in seconds.
    wait_max_s : float
        Maximum wait time between retries in seconds.
    wait_jitter : float
        Jitter fraction (0.0 to 1.0).
    wait_base : float
        Base multiplier for exponential backoff.
    metrics_label : str | None
        Label for metrics tracking.
    """

    name: str
    description: str | None
    methods: tuple[str, ...]
    retry_status: tuple[tuple[int, int] | int, ...]  # e.g., (500,504) or 429
    retry_exceptions: tuple[str, ...]
    give_up_status: tuple[int, ...]
    respect_retry_after: bool
    require_idempotency_key: bool
    stop_after_attempt: int
    stop_after_delay_s: float | None
    wait_kind: str
    wait_initial_s: float
    wait_max_s: float
    wait_jitter: float
    wait_base: float
    metrics_label: str | None


def _parse_status_entry(x: int | str) -> tuple[int, int] | int:
    """Parse status code entry from YAML (int or range string).

    Parameters
    ----------
    x : int | str
        Status code (int) or range string like "500-504".

    Returns
    -------
    tuple[int, int] | int
        Status code or range tuple.
    """
    if isinstance(x, int):
        return x
    lo, hi = x.split("-", 1)
    return (int(lo), int(hi))


def load_policy(path: Path, schema_path: Path | None = None) -> RetryPolicyDoc:
    """Load retry policy from YAML file.

    Parameters
    ----------
    path : Path
        Path to policy YAML file.
    schema_path : Path | None, optional
        Path to JSON schema for validation. Defaults to None.

    Returns
    -------
    RetryPolicyDoc
        Loaded policy document.

    Notes
    -----
    This function may propagate the following exceptions from dependencies:
    - ``FileNotFoundError``: If policy file does not exist (from ``path.read_text()``)
    - ``jsonschema.ValidationError``: If policy does not match schema
      (from ``jsonschema.validate()``)
    """
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if schema_path and schema_path.exists():
        jsonschema.validate(obj, json.loads(schema_path.read_text(encoding="utf-8")))
    return RetryPolicyDoc(
        name=obj["name"],
        description=obj.get("description"),
        methods=tuple(m.upper() for m in obj["methods"]),
        retry_status=tuple(_parse_status_entry(s) for s in obj["retry_on"].get("status", [])),
        retry_exceptions=tuple(obj["retry_on"].get("exceptions", [])),
        give_up_status=tuple(obj.get("give_up_on_status", [])),
        respect_retry_after=bool(obj.get("respect_retry_after", False)),
        require_idempotency_key=bool(obj.get("require_idempotency_key", False)),
        stop_after_attempt=int(obj["stop"]["after_attempt"]),
        stop_after_delay_s=(
            float(obj["stop"].get("after_delay_s"))
            if obj["stop"].get("after_delay_s") is not None
            else None
        ),
        wait_kind=obj["wait"]["kind"],
        wait_initial_s=float(obj["wait"]["initial_s"]),
        wait_max_s=float(obj["wait"]["max_s"]),
        wait_jitter=float(obj["wait"]["jitter"]),
        wait_base=float(obj["wait"].get("base", 2.0)),
        metrics_label=obj.get("metrics_label"),
    )


class PolicyRegistry:
    """Registry for loading retry policies from a directory.

    Parameters
    ----------
    root : Path
        Root directory containing policy YAML files.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, name: str) -> RetryPolicyDoc:
        """Load policy by name.

        Parameters
        ----------
        name : str
            Policy name (without .yaml extension).

        Returns
        -------
        RetryPolicyDoc
            Loaded policy document.

        Raises
        ------
        FileNotFoundError
            If policy file does not exist.
        """
        p = self.root / f"{name}.yaml"
        if not p.exists():
            raise FileNotFoundError(p)
        schema = Path(__file__).with_name("policy.schema.json")
        return load_policy(p, schema)
