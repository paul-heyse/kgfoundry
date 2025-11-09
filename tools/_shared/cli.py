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

    def _replace_envelope(envelope: CliEnvelope, **updates: object) -> CliEnvelope:
        return dataclass_replace(envelope, **updates)

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

    def _replace_envelope(envelope: CliEnvelope, **updates: object) -> CliEnvelope:
        return cast("CliEnvelope", structs.replace(envelope, **updates))


def new_cli_envelope(*, command: str, status: CliStatus, subcommand: str = "") -> CliEnvelope:
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


_SET_BUILDER_ATTR = object.__setattr__


@dataclass(slots=True, frozen=True)
class CliEnvelopeBuilder:
    """Fluent builder for assembling CLI envelopes."""

    envelope: CliEnvelope

    @classmethod
    def create(cls, *, command: str, status: CliStatus, subcommand: str = "") -> CliEnvelopeBuilder:
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
        return cls(new_cli_envelope(command=command, status=status, subcommand=subcommand))

    def _swap(self, *, update: CliEnvelope) -> CliEnvelopeBuilder:
        _SET_BUILDER_ATTR(self, "envelope", update)
        return self

    def add_file(
        self,
        *,
        path: str,
        status: CliFileStatus,
        message: str | None = None,
        problem: ProblemDetailsDict | None = None,
    ) -> CliEnvelopeBuilder:
        """Append a file-level result entry to the envelope.

        This method adds a file processing result to the envelope's files list,
        recording the file path, processing status, optional message, and any
        associated problem details. File entries are used to track individual
        file processing outcomes in batch operations.

        Parameters
        ----------
        path : str
            File path that was processed. This is the identifier for the file
            entry and should be a relative or absolute path string.
        status : CliFileStatus
            Processing status for the file. Must be one of: "success", "skipped",
            "error", or "violation". Determines how the file result is categorized.
        message : str | None, optional
            Optional human-readable message describing the file processing outcome.
            Provides additional context about why a file succeeded, was skipped,
            or failed. If None, no message is included. Defaults to None.
        problem : ProblemDetailsDict | None, optional
            Optional Problem Details dictionary associated with file processing
            failures or violations. Follows RFC 9457 format. If None, no problem
            details are attached. Defaults to None.

        Returns
        -------
        CliEnvelopeBuilder
            Builder instance for fluent chaining. Allows method calls to be
            chained together for building complex envelopes.
        """
        file_entry = CliFileResult(
            path=path,
            status=status,
            message=(message if message is not None else UNSET),
            problem=problem if problem is not None else UNSET,
        )
        updated_files = [*self.envelope.files, file_entry]
        return self._swap(update=_replace_envelope(self.envelope, files=updated_files))

    def add_error(
        self,
        *,
        status: CliErrorStatus,
        message: str,
        file: str | None = None,
        problem: ProblemDetailsDict | None = None,
    ) -> CliEnvelopeBuilder:
        """Record a build error with optional file attribution.

        This method adds an error-level entry to the envelope's errors list,
        recording error status, message, optional file attribution, and any
        associated problem details. Error entries represent non-file-specific
        failures or violations that occurred during CLI execution.

        Parameters
        ----------
        status : CliErrorStatus
            Error status category. Must be one of: "error", "violation", or
            "config". Determines how the error is categorized and affects
            overall envelope status.
        message : str
            Human-readable error message describing what went wrong. This is
            the primary error description and should be clear and actionable.
        file : str | None, optional
            Optional file path associated with the error. Used when an error
            is related to a specific file but doesn't warrant a file-level
            entry. If None, the error is considered global. Defaults to None.
        problem : ProblemDetailsDict | None, optional
            Optional Problem Details dictionary providing structured error
            information following RFC 9457 format. Includes error codes,
            types, and additional context. If None, no problem details are
            attached. Defaults to None.

        Returns
        -------
        CliEnvelopeBuilder
            Builder instance for fluent chaining. Allows method calls to be
            chained together for building complex envelopes.
        """
        error_entry = CliErrorEntry(
            status=status,
            message=message,
            file=(file if file is not None else UNSET),
            problem=problem if problem is not None else UNSET,
        )
        updated_errors = [*self.envelope.errors, error_entry]
        return self._swap(update=_replace_envelope(self.envelope, errors=updated_errors))

    def set_problem(self, problem: ProblemDetailsDict | None) -> CliEnvelopeBuilder:
        """Attach a Problem Details payload to the envelope.

        This method sets the top-level problem details for the envelope, which
        represents the primary error or failure that occurred during CLI execution.
        Problem details follow RFC 9457 format and provide structured error
        information including error codes, types, titles, and details.

        Parameters
        ----------
        problem : ProblemDetailsDict | None
            Problem Details dictionary following RFC 9457 format, or None to
            clear any existing problem details. When set, this becomes the
            primary error payload for the envelope. If None, the problem field
            is removed from the envelope.

        Returns
        -------
        CliEnvelopeBuilder
            Builder instance for fluent chaining. Allows method calls to be
            chained together for building complex envelopes.
        """
        replacement: ProblemDetailsDict | UnsetType = problem if problem is not None else UNSET
        return self._swap(update=_replace_envelope(self.envelope, problem=replacement))

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
        envelope = self.envelope
        if duration_seconds is not None:
            envelope = _replace_envelope(
                envelope,
                duration_seconds=float(duration_seconds),
            )
        validate_cli_envelope(envelope)
        return envelope


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
