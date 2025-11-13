"""Server-facing configuration for FastAPI + Hypercorn deployment.

This module centralizes HTTP listener parameters, CORS defaults, and proxy
trust knobs so deployments can be tuned via environment variables (or a
``.env`` file) without touching application code. The settings are consumed
by :mod:`codeintel_rev.app.main` when constructing the FastAPI application
and when exporting the Hypercorn-facing ASGI callable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    model_config : SettingsConfigDict | dict[str, object]
        Pydantic settings configuration dict. Configures pydantic-settings to
        load from .env (if present) and to use the CODEINTEL_SERVER_ prefix
        for environment variables. Also sets env_file_encoding to utf-8 and
        extra to "ignore". The attribute is assigned a SettingsConfigDict instance
        with env_file, env_file_encoding, env_prefix, and extra settings.
    """

    host: str = "127.0.0.1"
    port: int = 8080
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CODEINTEL_SERVER_",
        extra="ignore",
    )


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


__all__ = ["ServerSettings", "get_server_settings"]
