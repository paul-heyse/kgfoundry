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

    Parameters
    ----------
    host : str, default "127.0.0.1"
        Bind address used for local development (`make run-hypercorn`). In
        production Hypercorn typically listens on loopback while NGINX
        terminates TLS/QUIC.
    port : int, default 8080
        Application port when Hypercorn listens directly (Topology A).
    allowed_hosts : list[str], default ["localhost", "127.0.0.1"]
        Hostnames accepted by :class:`TrustedHostMiddleware`. Include public
        domains (e.g., ``mcp.example.com``) when running behind NGINX.
    cors_allow_origins : list[str], optional
        Origins permitted by the CORS middleware. Defaults to ChatGPT and
        localhost for local UI experiments.
    cors_allow_methods : list[str], optional
        HTTP verbs allowed via CORS preflight responses. ``["*"]`` keeps the
        configuration permissive while tooling evolves.
    cors_allow_headers : list[str], optional
        Headers allowed via CORS. Defaults to ``["*"]``.
    enable_trusted_hosts : bool, default True
        When ``True`` the FastAPI app installs :class:`TrustedHostMiddleware`.
    enable_proxy_fix : bool, default True
        When ``True`` the exported ASGI object is wrapped with
        :class:`hypercorn.middleware.ProxyFixMiddleware` so scheme/host/client
        information from NGINX is honored.
    proxy_mode : Literal["legacy","modern"], default "modern"
        ProxyFix mode. ``"modern"`` reads the standardized ``Forwarded``
        header; ``"legacy"`` falls back to ``X-Forwarded-*``.
    proxy_trusted_hops : int, default 1
        Number of proxy hops to trust when parsing ``Forwarded`` headers.
    domain : str | None, optional
        Canonical domain used in docs/runbooks. Does not affect runtime
        behavior but avoids duplicating values elsewhere.
    model_config : SettingsConfigDict
        Configures pydantic-settings to load from ``.env`` (if present) and
        to use the ``CODEINTEL_SERVER_`` prefix for environment variables.
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
