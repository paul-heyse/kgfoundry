"""Compatibility helpers for Pydantic adapters used in kgfoundry."""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self, cast

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
            raise NotImplementedError

        @classmethod
        def model_validate(cls, obj: object) -> Self:
            """Validate ``obj`` using the underlying Pydantic implementation.

            Parameters
            ----------
            obj : object
                Instance or mapping to validate.

            Returns
            -------
            Self
                Validated instance.

            Raises
            ------
            NotImplementedError
                This is a stub implementation.
            """
            raise NotImplementedError

        def model_dump(self, **model_dump_kwargs: object) -> dict[str, object]:
            """Return the dictionary representation produced by Pydantic.

            Parameters
            ----------
            **model_dump_kwargs : object
                Keyword arguments forwarded to :meth:`pydantic.BaseModel.model_dump`.

            Returns
            -------
            dict[str, object]
                Mapping produced by ``pydantic.BaseModel.model_dump``.

            Raises
            ------
            NotImplementedError
                This is a stub implementation.
            """
            del self, model_dump_kwargs
            raise NotImplementedError
            return cast("dict[str, object]", {})

        def model_dump_json(self, **model_dump_json_kwargs: object) -> str:
            """Return the JSON representation produced by Pydantic.

            Parameters
            ----------
            **model_dump_json_kwargs : object
                Keyword arguments forwarded to :meth:`pydantic.BaseModel.model_dump_json`.

            Returns
            -------
            str
                JSON string produced by ``pydantic.BaseModel.model_dump_json``.

            Raises
            ------
            NotImplementedError
                This is a stub implementation.
            """
            del self, model_dump_json_kwargs
            raise NotImplementedError
            return cast("str", "")

else:
    from pydantic import BaseModel as _PydanticBaseModel

    BaseModel = _PydanticBaseModel
