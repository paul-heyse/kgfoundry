"""Typed facades for jsonschema usage across the codebase.

This module centralizes imports from :mod:`jsonschema` so that static type checkers see
concrete types instead of ``Any``.  The upstream stubs expose several
untyped entry points (e.g. :class:`Draft202012Validator`,
:func:`jsonschema.validate`), so we wrap them with Protocol-based casts and
re-export the typed surfaces for internal use.
"""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import validate as _jsonschema_validate
from jsonschema.exceptions import SchemaError as _SchemaError
from jsonschema.exceptions import ValidationError as _ValidationError
from jsonschema.validators import Draft202012Validator as _Draft202012Validator

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


# [nav:anchor ValidationErrorProtocol]
class ValidationErrorProtocol(Protocol):
    """Typed view over ``jsonschema.exceptions.ValidationError`` instances."""

    message: str
    absolute_path: Sequence[object]
    path: Sequence[object]


# [nav:anchor Draft202012ValidatorProtocol]
class Draft202012ValidatorProtocol(Protocol):
    """Typed facade for :class:`jsonschema.validators.Draft202012Validator`.

    Parameters
    ----------
    schema : Mapping[str, object]
        JSON Schema document to validate against.
    *args : object
        Additional positional arguments passed to validator.
    **kwargs : object
        Additional keyword arguments passed to validator.
    """

    def __init__(self, schema: Mapping[str, object], *args: object, **kwargs: object) -> None: ...

    @classmethod
    def check_schema(cls, schema: Mapping[str, object]) -> None:
        """Validate that ``schema`` conforms to the Draft 2020-12 meta-schema."""
        ...

    def iter_errors(self, instance: object) -> Iterable[ValidationErrorProtocol]:
        """Yield validation errors for ``instance`` without raising."""
        ...

    def validate(self, instance: object) -> None:
        """Validate ``instance`` against the configured schema."""
        ...


# [nav:anchor Draft202012Validator]
Draft202012Validator = cast("type[Draft202012ValidatorProtocol]", _Draft202012Validator)
# [nav:anchor SchemaError]
SchemaError = cast("type[Exception]", _SchemaError)
# [nav:anchor ValidationError]
ValidationError = cast("type[Exception]", _ValidationError)


# [nav:anchor validate]
def validate(instance: object, schema: Mapping[str, object]) -> None:
    """Validate ``instance`` against ``schema`` using jsonschema."""
    _jsonschema_validate(instance=instance, schema=schema)


__all__ = [
    "Draft202012Validator",
    "Draft202012ValidatorProtocol",
    "SchemaError",
    "ValidationError",
    "ValidationErrorProtocol",
    "create_draft202012_validator",
    "validate",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor create_draft202012_validator]
def create_draft202012_validator(
    schema: Mapping[str, object],
) -> Draft202012ValidatorProtocol:
    """Return a typed Draft 2020-12 validator for ``schema``.

    Parameters
    ----------
    schema : Mapping[str, object]
        JSON Schema to validate against.

    Returns
    -------
    Draft202012ValidatorProtocol
        Typed validator instance.
    """
    concrete_schema = {str(key): value for key, value in schema.items()}
    validator_ctor = cast("Any", _Draft202012Validator)
    instance = validator_ctor(concrete_schema)
    return cast("Draft202012ValidatorProtocol", instance)
