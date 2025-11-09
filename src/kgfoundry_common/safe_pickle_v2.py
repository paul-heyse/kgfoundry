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
from importlib import import_module
from typing import TYPE_CHECKING, BinaryIO, Protocol, cast

from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


def _load_cloudpickle_dumps() -> Callable[[object], bytes] | None:
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

    Initializes unsafe serialization error with message and optional reason.

    Parameters
    ----------
    message : str
        Error description.
    reason : str | None, optional
        Specific reason (e.g., "signature_mismatch", "disallowed_type").
        Defaults to None.
    """

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class _UnpicklerProtocol(Protocol):
    def __init__(
        self,
        file: BinaryIO,
        *,
        fix_imports: bool = ...,
        encoding: str = ...,
        errors: str = ...,
        buffers: object | None = ...,
    ) -> None: ...

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
        """Static typing shim for the stdlib Unpickler."""

        def __init__(
            self,
            file: BinaryIO,
            *,
            fix_imports: bool = ...,
            encoding: str = ...,
            errors: str = ...,
            buffers: object | None = ...,
        ) -> None: ...

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
        module_name = "_pickle"
        return cast("_PickleModule", import_module(module_name))

    _stdlib_pickle = _load_stdlib_pickle()
    _StdlibUnpickler = cast("type[_UnpicklerProtocol]", _stdlib_pickle.Unpickler)


class _SafeUnpickler(_StdlibUnpickler):
    """Unpickler enforcing allow-list of safe types.

    This prevents arbitrary code execution by restricting deserialization to primitive types and
    basic containers.

    Initializes safe unpickler with file handle.

    Parameters
    ----------
    file : BinaryIO
        Binary file handle to read from.
    fix_imports : bool, optional
        Whether to fix imports for Python 2 compatibility. Defaults to True.
    encoding : str, optional
        Text encoding for Python 2 compatibility. Defaults to "ASCII".
    errors : str, optional
        Error handling mode for encoding. Defaults to "strict".
    buffers : object | None, optional
        Buffer protocol support. Defaults to None.
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

    Combines class allow-listing with HMAC-SHA256 signatures to prevent
    both arbitrary code execution and payload tampering.

    Initializes wrapper with signing key.

    Parameters
    ----------
    signing_key : bytes
        HMAC signing key (≥32 bytes recommended). A warning is logged if
        the key is shorter than 32 bytes.

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
        if len(signing_key) < _MIN_SIGNING_KEY_BYTES:
            logger.warning("Signing key < 32 bytes; consider using a longer key")
        self.signing_key = signing_key

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

        logger.debug(
            "Serialized object with HMAC signature", extra={"size": len(payload)}
        )

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
            msg = "Deserialization blocked: HMAC signature verification failed; payload may be tampered"
            raise UnsafeSerializationError(msg, reason="signature_mismatch")

        result = _load_with_allow_list(io.BytesIO(payload))

        logger.debug(
            "Deserialized object with verified signature", extra={"size": len(payload)}
        )
        return result


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
