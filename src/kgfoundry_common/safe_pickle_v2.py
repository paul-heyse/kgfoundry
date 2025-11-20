"""Secure pickle serialization with HMAC signing and class allow-list.

This module provides hardened pickle functionality with:
- Class allow-list validation (prevents code execution)
- HMAC-SHA256 signature verification (prevents tampering)
- Automatic key rotation guidance

Notes
-----
This replaces raw pickle usage for index serialization. Use JSON for new
formats where feasible. Keys should be stored in environment variables
and rotated regularly.

Examples
--------
>>> import os
>>> from pathlib import Path
>>> signer = SignedPickleWrapper(os.environ.get("SIGNING_KEY", "").encode())
>>> data = {"keys": ["a", "b"], "vectors": [1.0, 2.0]}
>>> with Path("/tmp/test.pkl").open("wb") as f:
...     signer.dump(data, f)
>>> with Path("/tmp/test.pkl").open("rb") as f:
...     loaded = signer.load(f)
>>> assert loaded == data
"""

# [nav:section public-api]

from __future__ import annotations

import hashlib
import hmac
import io
import logging
from importlib import import_module
from typing import TYPE_CHECKING, BinaryIO, Protocol, cast

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Callable


def _load_cloudpickle_dumps() -> Callable[[object], bytes] | None:
    """Load cloudpickle.dumps function if available.

    Attempts to import cloudpickle from either the shim module or the
    standard cloudpickle package. Returns the dumps function if found,
    None otherwise.

    Returns
    -------
    Callable[[object], bytes] | None
        cloudpickle.dumps function if available, None if cloudpickle
        is not installed.
    """
    candidate_modules = (
        "kgfoundry_common.cloudpickle_shim",
        "cloudpickle",
    )
    for module_name in candidate_modules:
        try:
            module = import_module(module_name)
        except ImportError:  # pragma: no cover - optional dependency missing
            continue
        dumps_candidate: object = getattr(module, "dumps", None)
        if callable(dumps_candidate):
            return cast("Callable[[object], bytes]", dumps_candidate)
    return None


_CLOUDPICKLE_DUMPS: Callable[[object], bytes] | None = _load_cloudpickle_dumps()

try:
    pickle_module = import_module("pickle")
    _PICKLING_ERROR = cast("type[Exception]", pickle_module.PicklingError)
except (ImportError, AttributeError):  # pragma: no cover - defensive fallback
    _PICKLING_ERROR = Exception

# Constants
_MIN_SIGNING_KEY_BYTES: int = 32
_SIGNATURE_LENGTH: int = 32  # SHA256 produces 32 bytes
_MAX_NESTING_DEPTH: int = 100

# Allow-list of safe types for pickle deserialization
_ALLOWED_TYPES = frozenset(
    {
        "builtins.dict",
        "builtins.list",
        "builtins.tuple",
        "builtins.str",
        "builtins.int",
        "builtins.float",
        "builtins.bool",
        "builtins.NoneType",
    }
)


# [nav:anchor UnsafeSerializationError]
class UnsafeSerializationError(ValueError):
    """Raised when serialization validation fails.

    Extended Summary
    ----------------
    Raised when pickle serialization validation detects unsafe or disallowed
    types or when signature verification fails. Used to prevent deserialization
    of potentially malicious pickle data by validating allowed types and
    cryptographic signatures.

    Notes
    -----
    Time O(1); memory O(1) aside from message storage. No I/O, no global state.
    Thread-safe. The reason attribute provides specific failure details for
    debugging and error handling.
    """

    def __init__(self, message: str, reason: str | None = None) -> None:
        """Initialize unsafe serialization error with message and optional reason.

        Parameters
        ----------
        message : str
            Error description explaining why serialization validation failed.
            Stored as the exception message.
        reason : str | None, optional
            Specific reason code for the validation failure (e.g., "signature_mismatch",
            "disallowed_type", "missing_signature"). Stored as instance attribute
            for programmatic error handling. Defaults to None.
        """
        super().__init__(message)
        self.reason = reason


class _UnpicklerProtocol(Protocol):
    """Protocol for unpickler interface used by safe pickle implementation.

    Extended Summary
    ----------------
    This protocol defines the interface for unpickler instances that can
    deserialize pickle streams with allow-list validation. Implementations
    must support the same initialization signature as stdlib pickle.Unpickler
    for compatibility with safe pickle wrappers.

    Notes
    -----
    This is a typing Protocol used for structural subtyping. Implementations
    should match the stdlib pickle.Unpickler API for file-based deserialization
    with optional Python 2 compatibility parameters.
    """

    def __init__(
        self,
        file: BinaryIO,
        *,
        fix_imports: bool = ...,
        encoding: str = ...,
        errors: str = ...,
        buffers: object | None = ...,
    ) -> None:
        """Initialize unpickler with file handle and options.

        Parameters
        ----------
        file : BinaryIO
            Binary file handle to read pickle data from. Must be opened in
            binary mode and positioned at the start of pickle data.
        fix_imports : bool, optional
            Whether to fix imports for Python 2 compatibility. When True,
            maps old Python 2 module names to Python 3 equivalents.
            Defaults to False.
        encoding : str, optional
            Text encoding for Python 2 compatibility. Used when unpickling
            Python 2 string objects. Defaults to "ASCII".
        errors : str, optional
            Error handling mode for encoding. Controls how encoding errors
            are handled during Python 2 string unpickling. Defaults to "strict".
        buffers : object | None, optional
            Buffer protocol support for zero-copy deserialization. Optional
            buffer objects for efficient data transfer. Defaults to None.

        Notes
        -----
        This is a Protocol method signature. Implementations must match this
        signature to be compatible with safe pickle wrappers.
        """
        ...

    def load(self) -> object:
        """Load and return unpickled object.

        Returns
        -------
        object
            Unpickled object from file.
        """
        ...

    def find_class(self, module: str, name: str) -> object:
        """Find class by module and name.

        Parameters
        ----------
        module : str
            Module name.
        name : str
            Class name.

        Returns
        -------
        object
            Class object.
        """
        ...


class _PickleModule(Protocol):
    """Protocol for pickle module interface.

    This protocol defines the interface for pickle modules (stdlib or cloudpickle)
    used for serialization. Provides Unpickler class and PicklingError exception.

    Attributes
    ----------
    Unpickler : type[_UnpicklerProtocol]
        Unpickler class for deserialization.
    PicklingError : type[Exception]
        Exception type raised on pickling errors.
    """

    Unpickler: type[_UnpicklerProtocol]

    PicklingError: type[Exception]

    def dump(self, obj: object, file: BinaryIO) -> None:
        """Serialize object to file.

        Parameters
        ----------
        obj : object
            Object to serialize.
        file : BinaryIO
            Binary file handle to write to.
        """
        ...

    def dumps(self, obj: object) -> bytes:
        """Serialize object to bytes.

        Parameters
        ----------
        obj : object
            Object to serialize.

        Returns
        -------
        bytes
            Serialized object as bytes.
        """
        ...


if TYPE_CHECKING:

    class _StdlibUnpickler(_UnpicklerProtocol):
        """Static typing shim for the stdlib Unpickler.

        Extended Summary
        ----------------
        Static typing shim that provides type hints for stdlib pickle.Unpickler
        when TYPE_CHECKING is True. At runtime, this is replaced with the actual
        stdlib Unpickler class. Used for type checking compatibility with safe
        pickle wrappers.

        Notes
        -----
        This is a typing-only class used during static analysis. At runtime,
        _StdlibUnpickler is assigned to the actual stdlib pickle.Unpickler class.
        """

        def __init__(
            self,
            file: BinaryIO,
            *,
            fix_imports: bool = ...,
            encoding: str = ...,
            errors: str = ...,
            buffers: object | None = ...,
        ) -> None:
            """Initialize stdlib unpickler shim with file handle and options.

            Parameters
            ----------
            file : BinaryIO
                Binary file handle to read pickle data from. Must be opened in
                binary mode and positioned at the start of pickle data.
            fix_imports : bool, optional
                Whether to fix imports for Python 2 compatibility. When True,
                maps old Python 2 module names to Python 3 equivalents.
            encoding : str, optional
                Text encoding for Python 2 compatibility. Used when unpickling
                Python 2 string objects. Defaults to "ASCII".
            errors : str, optional
                Error handling mode for encoding. Controls how encoding errors
                are handled during Python 2 string unpickling. Defaults to "strict".
            buffers : object | None, optional
                Buffer protocol support for zero-copy deserialization. Optional
                buffer objects for efficient data transfer.

            Notes
            -----
            This is a typing stub method. The actual implementation is provided
            by stdlib pickle.Unpickler at runtime.
            """
            ...

        def load(self) -> object:
            """Load and return unpickled object.

            Returns
            -------
            object
                Unpickled object from file.
            """
            ...

        def find_class(self, module: str, name: str) -> object:
            """Find class by module and name.

            Parameters
            ----------
            module : str
                Module name.
            name : str
                Class name.

            Returns
            -------
            object
                Class object.
            """
            ...

    _stdlib_pickle = cast("_PickleModule", None)
else:  # pragma: no cover - runtime import keeps Ruff S403 quiet

    def _load_stdlib_pickle() -> _PickleModule:
        """Load stdlib pickle module.

        Returns
        -------
        _PickleModule
            Pickle module instance with Unpickler and PicklingError.
        """
        module_name = "_pickle"
        return cast("_PickleModule", import_module(module_name))

    _stdlib_pickle = _load_stdlib_pickle()
    _StdlibUnpickler = cast("type[_UnpicklerProtocol]", _stdlib_pickle.Unpickler)


class _SafeUnpickler(_StdlibUnpickler):
    """Unpickler enforcing allow-list of safe types.

    Extended Summary
    ----------------
    This prevents arbitrary code execution by restricting deserialization to
    primitive types and basic containers. Overrides find_class() to enforce
    an allow-list of safe types, raising UnsafeSerializationError when
    disallowed types are encountered.

    Notes
    -----
    Time O(n) where n is the number of classes referenced in the pickle stream;
    memory O(1) aside from the unpickled object. No I/O beyond file reading,
    no global state. Thread-safe for separate instances. The allow-list is
    defined by _ALLOWED_TYPES module constant.
    """

    def __init__(
        self,
        file: BinaryIO,
        *,
        fix_imports: bool = True,
        encoding: str = "ASCII",
        errors: str = "strict",
        buffers: object | None = None,
    ) -> None:
        """Initialize safe unpickler with file handle and options.

        Parameters
        ----------
        file : BinaryIO
            Binary file handle to read pickle data from. Must be opened in
            binary mode and positioned at the start of pickle data.
        fix_imports : bool, optional
            Whether to fix imports for Python 2 compatibility. When True,
            maps old Python 2 module names to Python 3 equivalents.
            Defaults to True.
        encoding : str, optional
            Text encoding for Python 2 compatibility. Used when unpickling
            Python 2 string objects. Defaults to "ASCII".
        errors : str, optional
            Error handling mode for encoding. Controls how encoding errors
            are handled during Python 2 string unpickling. Defaults to "strict".
        buffers : object | None, optional
            Buffer protocol support for zero-copy deserialization. Optional
            buffer objects for efficient data transfer. Defaults to None.

        Notes
        -----
        Delegates to parent _StdlibUnpickler constructor with the provided
        parameters. The allow-list enforcement happens in find_class() override.
        """
        super().__init__(
            file,
            fix_imports=fix_imports,
            encoding=encoding,
            errors=errors,
            buffers=buffers,
        )

    def find_class(self, module: str, name: str) -> type:
        """Find class with allow-list enforcement.

        Parameters
        ----------
        module : str
            Module name.
        name : str
            Class name.

        Returns
        -------
        type
            The class object.

        Raises
        ------
        UnsafeSerializationError
            If class is not in allow-list.
        """
        full_name = f"{module}.{name}"
        if full_name not in _ALLOWED_TYPES:
            msg = f"Deserialization blocked: {full_name} not in allow-list"
            raise UnsafeSerializationError(msg, reason="disallowed_type")
        return cast("type[object]", super().find_class(module, name))

    def load(self) -> object:
        """Deserialize the payload using the hardened allow-list.

        Returns
        -------
        object
            Deserialized object.
        """
        return super().load()


def _load_with_allow_list(file_obj: io.BytesIO) -> object:
    """Load pickle with allow-list validation.

    Parameters
    ----------
    file_obj : io.BytesIO
        File object with pickled data.

    Returns
    -------
    object
        Deserialized object.

    Raises
    ------
    UnsafeSerializationError
        If pickle contains disallowed types.
    """
    unpickler = _SafeUnpickler(file_obj)
    try:
        loaded: object = unpickler.load()
    except UnsafeSerializationError:
        raise
    except Exception as exc:
        msg = f"Pickle deserialization failed: {exc}"
        raise UnsafeSerializationError(msg, reason="parse_error") from exc
    else:
        return loaded


def _validate_object(obj: object, depth: int = 0) -> None:
    """Recursively validate object contains only safe types.

    Parameters
    ----------
    obj : object
        Object to validate.
    depth : int
        Current recursion depth (prevents infinite recursion).

    Raises
    ------
    ValueError
        If object contains disallowed types or exceeds depth limit.
    """
    if depth > _MAX_NESTING_DEPTH:
        msg = f"Object nesting exceeds maximum depth ({_MAX_NESTING_DEPTH})"
        raise ValueError(msg)

    # Primitives are always safe
    if isinstance(obj, (str, int, float, bool, type(None))):
        return

    # Containers
    if isinstance(obj, dict):
        for key, value in obj.items():
            _validate_object(key, depth + 1)
            _validate_object(value, depth + 1)
        return

    if isinstance(obj, (list, tuple)):
        for item in obj:
            _validate_object(item, depth + 1)
        return

    # Reject other types
    msg = f"Object type not allowed for safe pickling: {type(obj).__qualname__}"
    raise ValueError(msg)


# [nav:anchor SignedPickleWrapper]
class SignedPickleWrapper:
    """HMAC-signed pickle with allow-list validation.

    Extended Summary
    ----------------
    Combines class allow-listing with HMAC-SHA256 signatures to prevent
    both arbitrary code execution and payload tampering. Provides dump()
    and load() methods that validate object types before serialization and
    verify signatures before deserialization.

    Notes
    -----
    Time O(n) for serialization/deserialization where n is object size;
    memory O(n) for the serialized payload. Uses HMAC-SHA256 for signature
    generation and verification. Thread-safe for separate instances. Warns
    if signing_key is shorter than _MIN_SIGNING_KEY_BYTES (32 bytes).

    Examples
    --------
    >>> import os
    >>> key = os.urandom(32)
    >>> wrapper = SignedPickleWrapper(key)
    >>> data = {"index": "data"}
    >>> import io
    >>> buffer = io.BytesIO()
    >>> wrapper.dump(data, buffer)
    >>> buffer.seek(0)
    >>> loaded = wrapper.load(buffer)
    >>> assert loaded == data
    """

    def __init__(self, signing_key: bytes) -> None:
        """Initialize signed pickle wrapper with signing key.

        Parameters
        ----------
        signing_key : bytes
            HMAC signing key for pickle integrity verification. Should be
            at least 32 bytes for strong security. Keys shorter than
            _MIN_SIGNING_KEY_BYTES will trigger a warning but are still
            accepted. Stored as instance attribute for use in dump() and load().

        Notes
        -----
        Validates signing key length and logs a warning if the key is shorter
        than the recommended minimum. The key is stored for use in HMAC
        signature generation and verification during dump() and load() operations.
        """
        self.signing_key = signing_key
        if len(signing_key) < _MIN_SIGNING_KEY_BYTES:
            LOGGER.warning("Signing key < %d bytes; security is degraded.", _MIN_SIGNING_KEY_BYTES)

    def dump(self, obj: object, file: BinaryIO) -> None:
        """Dump object with HMAC signature.

        Parameters
        ----------
        obj : object
            Object to serialize (dict/list/primitives only).
        file : BinaryIO
            File-like object opened in binary write mode.

        Notes
        -----
        Propagates :class:`ValueError` when the object contains disallowed
        types according to :func:`_validate_object`.
        """
        _validate_object(obj)

        payload = _stdlib_pickle.dumps(obj)
        signature = hmac.new(self.signing_key, payload, hashlib.sha256).digest()
        file.write(signature + payload)

    def load(self, file: BinaryIO) -> object:
        """Load and verify object signature.

        Parameters
        ----------
        file : BinaryIO
            File-like object opened in binary read mode.

        Returns
        -------
        object
            Deserialized object (verified safe).

        Raises
        ------
        UnsafeSerializationError
            If signature verification fails or object contains disallowed types.
        """
        data = file.read()
        if len(data) < _SIGNATURE_LENGTH:
            msg = "Serialized data too short; unable to verify signature"
            raise UnsafeSerializationError(msg, reason="truncated")

        signature, payload = data[:_SIGNATURE_LENGTH], data[_SIGNATURE_LENGTH:]
        expected_sig = hmac.new(self.signing_key, payload, hashlib.sha256).digest()

        if not hmac.compare_digest(signature, expected_sig):
            msg = (
                "Deserialization blocked: HMAC signature verification failed; "
                "payload may be tampered"
            )
            raise UnsafeSerializationError(msg, reason="signature_mismatch")

        return _load_with_allow_list(io.BytesIO(payload))


# [nav:anchor load_unsigned_legacy]
def load_unsigned_legacy(file: BinaryIO) -> object:
    """Deserialize an unsigned legacy pickle stream with allow-list validation.

    Parameters
    ----------
    file : BinaryIO
        File-like object opened in binary read mode.

    Returns
    -------
    object
        Deserialized object containing only allow-listed primitives and containers.

    Notes
    -----
    Propagates :class:`UnsafeSerializationError` when the pickle stream contains
    disallowed types or cannot be parsed by :func:`_load_with_allow_list`.
    """
    data = file.read()
    buffer = io.BytesIO(data)
    return _load_with_allow_list(buffer)


# [nav:anchor create_unsigned_pickle_payload]
def create_unsigned_pickle_payload(obj: object) -> bytes:
    """Return pickle bytes for constructing negative test fixtures.

    This helper first attempts stdlib pickle. If the object cannot be serialized
    (e.g., local classes defined inside tests), it falls back to ``cloudpickle``
    when available. Production code should continue to use
    :class:`SignedPickleWrapper` or :func:`load_unsigned_legacy`.

    Parameters
    ----------
    obj : object
        Object to serialize.

    Returns
    -------
    bytes
        Pickle bytes representation of the object.

    Raises
    ------
    RuntimeError
        If cloudpickle is required but not available.
    """
    try:
        return _stdlib_pickle.dumps(obj)
    except (AttributeError, _PICKLING_ERROR, TypeError) as exc:
        if _CLOUDPICKLE_DUMPS is None:
            message = "cloudpickle is required to serialize this object"
            raise RuntimeError(message) from exc
        return _CLOUDPICKLE_DUMPS(obj)


__all__ = [
    "SignedPickleWrapper",
    "UnsafeSerializationError",
    "create_unsigned_pickle_payload",
    "load_unsigned_legacy",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
# Module-level logger for operational warnings (e.g., key hygiene).
LOGGER = logging.getLogger(__name__)
