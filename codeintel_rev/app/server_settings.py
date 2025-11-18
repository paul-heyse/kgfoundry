"""Server-facing configuration for FastAPI + Hypercorn deployment.

This module centralizes HTTP listener parameters, CORS defaults, and proxy
trust knobs so deployments can be tuned via environment variables (or a
``.env`` file) without touching application code. The settings are consumed
by :mod:`codeintel_rev.app.main` when constructing the FastAPI application
and when exporting the Hypercorn-facing ASGI callable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SSE_KEEPALIVE_SECONDS = 25.0
_MIN_SSE_KEEPALIVE_SECONDS = 5.0


class ServerSettings(BaseSettings):
    """Container for server/network level toggles.

    This class centralizes HTTP listener parameters, CORS defaults, and proxy
    trust knobs for FastAPI + Hypercorn deployment. Settings are loaded from
    environment variables (with CODEINTEL_SERVER_ prefix) or a .env file.
    The settings are consumed by the FastAPI application and Hypercorn ASGI
    callable for server configuration.

    Attributes
    ----------
    host : str
        Bind address used for local development (default: "127.0.0.1"). In
        production Hypercorn typically listens on loopback while NGINX
        terminates TLS/QUIC.
    port : int
        Application port when Hypercorn listens directly (default: 8080).
        Used for Topology A deployments where Hypercorn is the direct listener.
    allowed_hosts : list[str]
        Hostnames accepted by TrustedHostMiddleware (default: ["localhost", "127.0.0.1"]).
        Include public domains (e.g., "mcp.example.com") when running behind NGINX.
    cors_allow_origins : list[str]
        Origins permitted by the CORS middleware (default: ["https://chat.openai.com", "http://localhost:3000"]).
        Defaults to ChatGPT and localhost for local UI experiments.
    cors_allow_methods : list[str]
        HTTP verbs allowed via CORS preflight responses (default: ["*"]).
        Keeps the configuration permissive while tooling evolves.
    cors_allow_headers : list[str]
        Headers allowed via CORS (default: ["*"]). Permissive default for
        development and tooling compatibility.
    cors_allow_credentials : bool
        Whether to allow credentials in CORS requests (default: True).
        Enables cookies and authentication headers in cross-origin requests.
    enable_trusted_hosts : bool
        When True (default), the FastAPI app installs TrustedHostMiddleware.
        Validates Host headers against allowed_hosts to prevent host header
        injection attacks.
    enable_proxy_fix : bool
        When True (default), the exported ASGI object is wrapped with
        ProxyFixMiddleware so scheme/host/client information from NGINX
        is honored. Required when running behind a reverse proxy.
    proxy_mode : Literal["legacy", "modern"]
        ProxyFix mode (default: "modern"). "modern" reads the standardized
        Forwarded header; "legacy" falls back to X-Forwarded-* headers.
    proxy_trusted_hops : int
        Number of proxy hops to trust when parsing Forwarded headers (default: 1).
        Used by ProxyFixMiddleware to validate proxy chain length.
    domain : str | None
        Canonical domain used in docs/runbooks (default: None). Does not affect
        runtime behavior but avoids duplicating values elsewhere. Optional
        metadata field for documentation purposes.
    sse_keepalive_seconds : float
        SSE keep-alive interval in seconds (default: 25.0). Minimum value is 5.0
        seconds, enforced by validator. Used to send periodic keep-alive frames
        in Server-Sent Events streams to prevent connection timeouts.
    sse_max_keepalives : int | None
        Optional cap on keep-alive frames for long-lived SSE streams (default: None).
        If set, limits the number of keep-alive frames sent before closing the stream.
        None disables the cap. Negative values are treated as None.
    model_config : ClassVar[SettingsConfigDict]
        Pydantic settings configuration dict. Configures pydantic-settings to
        load from .env (if present) and to use the CODEINTEL_SERVER_ prefix
        for environment variables. Also sets env_file_encoding to utf-8 and
        extra to "ignore". The attribute is assigned a SettingsConfigDict instance
        with env_file, env_file_encoding, env_prefix, and extra settings.
        This is a class variable (ClassVar) used by Pydantic BaseSettings.
    """

    host: str = "127.0.0.1"
    port: int = 8080
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "https://chat.openai.com",
            "http://localhost:3000",
        ]
    )
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = True
    enable_trusted_hosts: bool = True
    enable_proxy_fix: bool = True
    proxy_mode: Literal["legacy", "modern"] = "modern"
    proxy_trusted_hops: int = 1
    domain: str | None = None
    sse_keepalive_seconds: float = Field(default=_DEFAULT_SSE_KEEPALIVE_SECONDS)
    sse_max_keepalives: int | None = None

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CODEINTEL_SERVER_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_keepalive_interval(self) -> ServerSettings:
        """Enforce minimum SSE keep-alive interval.

        Returns
        -------
        ServerSettings
            Self instance with sse_keepalive_seconds clamped to minimum value.

        Notes
        -----
        Ensures sse_keepalive_seconds is at least _MIN_SSE_KEEPALIVE_SECONDS
        (5.0 seconds) to prevent connection timeouts. Values below the minimum
        are automatically adjusted upward.
        """
        self.sse_keepalive_seconds = max(self.sse_keepalive_seconds, _MIN_SSE_KEEPALIVE_SECONDS)
        return self


@lru_cache
def get_server_settings() -> ServerSettings:
    """Return (and cache) :class:`ServerSettings` for reuse.

    The LRU cache ensures settings are parsed only once per interpreter run,
    mirroring FastAPI's preferred configuration pattern.

    Returns
    -------
    ServerSettings
        Parsed configuration object.
    """
    return ServerSettings()


__all__ = ["_DEFAULT_SSE_KEEPALIVE_SECONDS", "ServerSettings", "get_server_settings"]
