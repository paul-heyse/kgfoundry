"""Typed CLI envelope models and helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

import msgspec
from msgspec import UNSET, Struct, structs

from kgfoundry_common.typing import gate_import
from tools._shared.schema import validate_tools_payload

type CliStatus = Literal["success", "violation", "config", "error"]
type CliFileStatus = Literal["success", "skipped", "error", "violation"]
type CliErrorStatus = Literal["error", "violation", "config"]

CLI_ENVELOPE_SCHEMA = "cli_envelope.json"
CLI_ENVELOPE_SCHEMA_VERSION = "1.0.0"
CLI_ENVELOPE_SCHEMA_ID = "https://kgfoundry.dev/schema/cli-envelope.json"


if TYPE_CHECKING:
    from dataclasses import field
    from dataclasses import replace as dataclass_replace

    from msgspec import UnsetType

    from tools._shared.problem_details import ProblemDetailsDict

    @dataclass(slots=True, frozen=True)
    class CliFileResult:
        """Individual file processing result emitted by tooling CLIs."""

        path: str
        status: CliFileStatus
        message: str | UnsetType = UNSET
        problem: ProblemDetailsDict | UnsetType = UNSET

    @dataclass(slots=True, frozen=True)
    class CliErrorEntry:
        """Error-level entry attached to CLI envelopes."""

        status: CliErrorStatus
        message: str
        file: str | UnsetType = UNSET
        problem: ProblemDetailsDict | UnsetType = UNSET

    @dataclass(slots=True, frozen=True)
    class CliEnvelope:
        """Typed representation of ``schema/tools/cli_envelope.json``."""

        schema_version: str = CLI_ENVELOPE_SCHEMA_VERSION
        schema_id: str = CLI_ENVELOPE_SCHEMA_ID
        generated_at: str = field(default_factory=datetime.now(tz=UTC).isoformat)
        status: CliStatus = "success"
        command: str = ""
        subcommand: str = ""
        duration_seconds: float = 0.0
        files: list[CliFileResult] = field(default_factory=list)
        errors: list[CliErrorEntry] = field(default_factory=list)
        problem: ProblemDetailsDict | UnsetType = UNSET

else:
    problem_details_module = gate_import(
        "tools._shared.problem_details",
        "CLI envelope problem details typing",
    )
    ProblemDetailsDict = problem_details_module.ProblemDetailsDict

    class CliFileResult(Struct, kw_only=True):
        """Individual file processing result emitted by tooling CLIs."""

        path: str
        status: CliFileStatus
        message: str | UnsetType = UNSET
        problem: ProblemDetailsDict | UnsetType = UNSET

    class CliErrorEntry(Struct, kw_only=True):
        """Error-level entry attached to CLI envelopes."""

        status: CliErrorStatus
        message: str
        file: str | UnsetType = UNSET
        problem: ProblemDetailsDict | UnsetType = UNSET

    def _default_generated_at() -> str:
        return datetime.now(tz=UTC).isoformat()

    def _default_files() -> list[CliFileResult]:
        return []

    def _default_errors() -> list[CliErrorEntry]:
        return []

    class CliEnvelope(Struct, kw_only=True):
        """Typed representation of ``schema/tools/cli_envelope.json``."""

        schema_version: str = msgspec.field(
            default=CLI_ENVELOPE_SCHEMA_VERSION,
            name="schemaVersion",
        )
        schema_id: str = msgspec.field(
            default=CLI_ENVELOPE_SCHEMA_ID,
            name="schemaId",
        )
        generated_at: str = msgspec.field(
            default_factory=_default_generated_at,
            name="generatedAt",
        )
        status: CliStatus = "success"
        command: str = ""
        subcommand: str = ""
        duration_seconds: float = msgspec.field(default=0.0, name="durationSeconds")
        files: list[CliFileResult] = msgspec.field(default_factory=_default_files)
        errors: list[CliErrorEntry] = msgspec.field(default_factory=_default_errors)
        problem: ProblemDetailsDict | UnsetType = UNSET


def new_cli_envelope(
    *, command: str, status: CliStatus, subcommand: str = ""
) -> CliEnvelope:
    """Return a freshly initialised CLI envelope.

    Parameters
    ----------
    command : str
        Command name.
    status : CliStatus
        Status code for the command.
    subcommand : str, optional
        Optional subcommand name. Defaults to empty string.

    Returns
    -------
    CliEnvelope
        Envelope populated with the required metadata for ``status``.
    """
    return CliEnvelope(command=command, status=status, subcommand=subcommand)


def validate_cli_envelope(envelope: CliEnvelope) -> None:
    """Validate ``envelope`` against the CLI schema.

    This function calls ``validate_tools_payload`` which may raise validation
    errors. See :func:`tools._shared.schema.validate_tools_payload` for details.
    """
    payload: dict[str, object] = msgspec.to_builtins(envelope)
    validate_tools_payload(payload, CLI_ENVELOPE_SCHEMA)


def render_cli_envelope(envelope: CliEnvelope, *, indent: int = 2) -> str:
    """Return a JSON string for ``envelope``.

    Parameters
    ----------
    envelope : CliEnvelope
        CLI envelope to serialize.
    indent : int, optional
        JSON indentation level. Default is 2.

    Returns
    -------
    str
        JSON-encoded envelope string.
    """
    payload: dict[str, object] = msgspec.to_builtins(envelope)
    return json.dumps(payload, indent=indent)


@dataclass(slots=True, frozen=True)
class CliEnvelopeBuilder:
    """Mutable builder for assembling CLI envelopes."""

    envelope: CliEnvelope

    @classmethod
    def create(
        cls, *, command: str, status: CliStatus, subcommand: str = ""
    ) -> CliEnvelopeBuilder:
        """Instantiate a builder for ``command`` with the provided status.

        Parameters
        ----------
        command : str
            Command name.
        status : CliStatus
            Initial status for the envelope.
        subcommand : str, optional
            Optional subcommand name. Default is empty string.

        Returns
        -------
        CliEnvelopeBuilder
            New builder instance.
        """
        return cls(
            new_cli_envelope(command=command, status=status, subcommand=subcommand)
        )

    def add_file(
        self,
        *,
        path: str,
        status: CliFileStatus,
        message: str | None = None,
        problem: ProblemDetailsDict | None = None,
    ) -> None:
        """Append a file-level result entry to the envelope."""
        self.envelope.files.append(
            CliFileResult(
                path=path,
                status=status,
                message=(message if message is not None else UNSET),
                problem=problem if problem is not None else UNSET,
            )
        )

    def add_error(
        self,
        *,
        status: CliErrorStatus,
        message: str,
        file: str | None = None,
        problem: ProblemDetailsDict | None = None,
    ) -> None:
        """Record a build error with optional file attribution."""
        self.envelope.errors.append(
            CliErrorEntry(
                status=status,
                message=message,
                file=(file if file is not None else UNSET),
                problem=problem if problem is not None else UNSET,
            )
        )

    def set_problem(self, problem: ProblemDetailsDict | None) -> None:
        """Attach a Problem Details payload to the envelope."""
        replacement: ProblemDetailsDict | UnsetType = (
            problem if problem is not None else UNSET
        )
        if TYPE_CHECKING:
            self.envelope = dataclass_replace(self.envelope, problem=replacement)
        else:
            self.envelope = cast(
                "CliEnvelope",
                structs.replace(self.envelope, problem=replacement),
            )

    def finish(self, *, duration_seconds: float | None = None) -> CliEnvelope:
        """Finalize the envelope, validating it before returning.

        Parameters
        ----------
        duration_seconds : float | None, optional
            Optional execution duration in seconds.

        Returns
        -------
        CliEnvelope
            Validated and finalized envelope.

        Note
        ----
        This function calls ``validate_cli_envelope`` which may raise validation
        errors. See :func:`validate_cli_envelope` for details.
        """
        if duration_seconds is not None:
            if TYPE_CHECKING:
                self.envelope = dataclass_replace(
                    self.envelope,
                    duration_seconds=float(duration_seconds),
                )
            else:
                self.envelope = cast(
                    "CliEnvelope",
                    structs.replace(
                        self.envelope,
                        duration_seconds=float(duration_seconds),
                    ),
                )
        validate_cli_envelope(self.envelope)
        return self.envelope


__all__ = [
    "CLI_ENVELOPE_SCHEMA",
    "CLI_ENVELOPE_SCHEMA_ID",
    "CLI_ENVELOPE_SCHEMA_VERSION",
    "CliEnvelope",
    "CliEnvelopeBuilder",
    "CliErrorEntry",
    "CliErrorStatus",
    "CliFileResult",
    "CliFileStatus",
    "CliStatus",
    "new_cli_envelope",
    "render_cli_envelope",
    "validate_cli_envelope",
]
