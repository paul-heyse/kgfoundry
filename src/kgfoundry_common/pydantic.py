"""Compatibility helpers for Pydantic adapters used in kgfoundry."""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

if TYPE_CHECKING:
    # [nav:anchor BaseModel]
    class BaseModel:
        """Typing-friendly stub that mirrors Pydantic's ``BaseModel``.

        Populates the model from keyword arguments.

        Parameters
        ----------
        **data : object
            Keyword arguments accepted by the Pydantic model.

        Attributes
        ----------
        model_config : ClassVar[object]
            Pydantic model configuration dictionary.

        Raises
        ------
        NotImplementedError
            This is a stub implementation.
        """

        model_config: ClassVar[object]

        def __init__(self, **data: object) -> None:
            """Initialize Pydantic model stub.

            Parameters
            ----------
            **data : object
                Model field values.

            Raises
            ------
            NotImplementedError
                This is a stub implementation.
            """
            raise NotImplementedError

        @classmethod
        def model_validate(cls, obj: object) -> Self:
            """Validate ``obj`` using the underlying Pydantic implementation."""
            raise NotImplementedError

        def model_dump(self, **_model_dump_kwargs: object) -> dict[str, object]:
            """Return the dictionary representation produced by Pydantic."""
            raise NotImplementedError

        def model_dump_json(self, **_model_dump_json_kwargs: object) -> str:
            """Return the JSON representation produced by Pydantic."""
            raise NotImplementedError

else:
    from pydantic import BaseModel as _PydanticBaseModel

    BaseModel = _PydanticBaseModel
