"""Heuristics for toggling RM3 pseudo-relevance feedback per query."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["RM3Heuristics", "RM3Params"]


@dataclass(frozen=True)
class RM3Params:
    """Default RM3 parameters used when pseudo-relevance feedback is enabled.

    Attributes
    ----------
    fb_docs : int, optional
        Number of feedback documents to use for RM3 expansion. Must be positive.
        Defaults to 10.
    fb_terms : int, optional
        Number of feedback terms to extract from top documents. Must be positive.
        Defaults to 10.
    orig_weight : float, optional
        Weight for the original query in RM3 (0.0 to 1.0). Higher values give
        more weight to the original query. Defaults to 0.5.
    """

    fb_docs: int = 10
    fb_terms: int = 10
    orig_weight: float = 0.5


class RM3Heuristics:
    """Lightweight heuristics to decide when RM3 should be enabled for a query."""

    _DEFAULT_SYMBOL_RE = (
        r"(?:\w+::\w+)|"  # namespaces / scopes
        r"(?:\w+\.\w+)|"  # dotted imports
        r"(?:[/\\])|"  # paths
        r"(?:[A-Za-z]+[A-Z][a-z]+)|"  # camelCase / PascalCase
        r"(?:[A-Za-z_]+\d+)"  # identifiers with digits
    )
    _DEFAULT_HEAD_TERMS = (
        "how",
        "find",
        "where",
        "get",
        "set",
        "create",
        "update",
        "delete",
        "auth",
        "login",
        "error",
        "bug",
        "serialize",
        "deserialize",
        "connect",
        "database",
        "config",
        "configuration",
        "path",
        "file",
        "read",
        "write",
        "parse",
        "build",
        "test",
        "mock",
        "client",
        "server",
        "handle",
        "exception",
        "timeout",
    )

    def __init__(
        self,
        *,
        short_query_max_terms: int = 3,
        symbol_like_regex: str | None = None,
        head_terms: Iterable[str] | None = None,
        default_params: RM3Params | None = None,
    ) -> None:
        """Initialize RM3 heuristics.

        Parameters
        ----------
        short_query_max_terms : int, optional
            Maximum terms for a query to be considered "short" (default: 3).
        symbol_like_regex : str | None, optional
            Custom regex for detecting symbol-like queries. If None, uses default pattern.
        head_terms : Iterable[str] | None, optional
            Terms that should trigger RM3 (e.g., ["build", "test"]).
        default_params : RM3Params | None, optional
            Default RM3 parameters when enabled.
        """
        self._short_query_max_terms = max(1, short_query_max_terms)
        pattern = symbol_like_regex or self._DEFAULT_SYMBOL_RE
        self._symbol_regex = re.compile(pattern)
        terms = []
        if head_terms:
            terms.extend(head_terms)
        else:
            terms.extend(self._DEFAULT_HEAD_TERMS)
        self._head_terms = {term.strip().lower() for term in terms if term and term.strip()}
        self._default_params = default_params or RM3Params()

    @staticmethod
    def _tokenize(query: str) -> list[str]:
        """Tokenize query text into lowercase alphanumeric tokens.

        Parameters
        ----------
        query : str
            Query string to tokenize.

        Returns
        -------
        list[str]
            List of non-empty tokens extracted from the query, converted to
            lowercase. Tokens consist of alphanumeric characters and underscores.
        """
        return [token for token in re.split(r"[^A-Za-z0-9_]+", query.lower()) if token]

    def _looks_symbolic(self, query: str) -> bool:
        """Check if query contains symbol-like patterns.

        Parameters
        ----------
        query : str
            Query string to check for symbolic patterns.

        Returns
        -------
        bool
            True if the query matches symbol-like patterns (namespaces, dotted
            imports, paths, camelCase/PascalCase, identifiers with digits),
            False otherwise.
        """
        return bool(self._symbol_regex.search(query))

    def should_enable(self, query: str) -> bool:
        """Return ``True`` when RM3 should be used for ``query``.

        Parameters
        ----------
        query : str
            Search query string to evaluate.

        Returns
        -------
        bool
            True if RM3 should be enabled based on query characteristics (short
            queries, presence of head terms, non-symbolic queries), False otherwise.
        """
        if not query:
            return False
        tokens = self._tokenize(query)
        if len(tokens) <= self._short_query_max_terms:
            return True
        if self._looks_symbolic(query):
            return False
        return any(token in self._head_terms for token in tokens)

    def parameters(self) -> RM3Params:
        """Return the RM3 parameters associated with this heuristic.

        Returns
        -------
        RM3Params
            RM3 parameter configuration (expansion terms, original query weight,
            etc.) used when RM3 is enabled.
        """
        return self._default_params
