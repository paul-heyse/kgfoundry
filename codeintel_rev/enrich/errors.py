# SPDX-License-Identifier: MIT
"""Typed exceptions for enrichment pipeline stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AnalyticsError",
    "DiscoveryError",
    "IndexingError",
    "IngestError",
    "OutputError",
    "StageError",
    "TaggingError",
    "TypeSignalError",
]


@dataclass(slots=True, frozen=True)
class StageError(Exception):
    """Base error describing a failed enrichment stage."""

    stage: str
    reason: str
    path: str | None = None
    detail: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def token(self) -> str:
        """Return a compact token suitable for embedding in module rows.

        Returns
        -------
        str
            Stage-prefixed string capturing the error reason.
        """
        payload = [self.stage, self.reason]
        if self.detail:
            payload.append(self.detail)
        if self.path:
            payload.append(self.path)
        return "|".join(str(part) for part in payload if part)

    def log_extra(self) -> dict[str, Any]:
        """Return structured metadata for logging.

        Returns
        -------
        dict[str, Any]
            Dictionary safe for structured logging calls.
        """
        extras: dict[str, Any] = {"stage": self.stage, "reason": self.reason}
        if self.path:
            extras["path"] = self.path
        if self.detail:
            extras["detail"] = self.detail
        extras.update(self.data)
        return extras


class DiscoveryError(StageError):
    """Raised when repository discovery/globbing fails."""

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        detail: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("discover", reason, path=path, detail=detail, data=data or {})


class IngestError(StageError):
    """Raised when ingestion of SCIP/FS artifacts fails."""

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        detail: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("ingest", reason, path=path, detail=detail, data=data or {})


class IndexingError(StageError):
    """Raised when LibCST/Tree-sitter indexing fails for a module."""

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        detail: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("index", reason, path=path, detail=detail, data=data or {})


class TypeSignalError(StageError):
    """Raised when collecting type checker summaries fails."""

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        detail: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("type-signals", reason, path=path, detail=detail, data=data or {})


class TaggingError(StageError):
    """Raised when tagging rules fail to evaluate."""

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        detail: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("tagging", reason, path=path, detail=detail, data=data or {})


class AnalyticsError(StageError):
    """Raised when analytics or derived metrics fail to compute."""

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        detail: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("analytics", reason, path=path, detail=detail, data=data or {})


class OutputError(StageError):
    """Raised when serializing enrichment outputs fails."""

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        detail: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("write", reason, path=path, detail=detail, data=data or {})
