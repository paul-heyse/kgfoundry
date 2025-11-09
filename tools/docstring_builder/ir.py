"""Intermediate representation for generated docstrings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from pathlib import Path

    from tools.docstring_builder.semantics import SemanticResult

IR_VERSION = "1.0"


@dataclass(slots=True, frozen=True)
class IRParameter:
    """Parameter entry stored in the docstring IR."""

    name: str
    annotation: str | None
    optional: bool
    default: str | None
    description: str
    kind: str
    display_name: str | None


@dataclass(slots=True, frozen=True)
class IRReturn:
    """Return or yield entry stored in the docstring IR."""

    annotation: str | None
    description: str
    kind: Literal["returns", "yields"]


@dataclass(slots=True, frozen=True)
class IRRaise:
    """Exception metadata stored in the docstring IR."""

    exception: str
    description: str


@dataclass(slots=True, frozen=True)
class IRDocstring:
    """Top-level representation of a generated docstring."""

    symbol_id: str
    module: str
    kind: str
    source_path: str
    lineno: int
    ir_version: str = IR_VERSION
    summary: str = ""
    extended: str | None = None
    parameters: list[IRParameter] = field(default_factory=list)
    returns: list[IRReturn] = field(default_factory=list)
    raises: list[IRRaise] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_ir(entry: SemanticResult) -> IRDocstring:
    """Convert a :class:`SemanticResult` into an :class:`IRDocstring`.

    Parameters
    ----------
    entry : SemanticResult
        Semantic result containing symbol and schema information.

    Returns
    -------
    IRDocstring
        Intermediate representation docstring instance.
    """
    symbol = entry.symbol
    schema = entry.schema
    parameters = [
        IRParameter(
            name=parameter.name,
            annotation=parameter.annotation,
            optional=parameter.optional,
            default=parameter.default,
            description=parameter.description,
            kind=parameter.kind,
            display_name=parameter.display_name,
        )
        for parameter in schema.parameters
    ]
    returns = [
        IRReturn(annotation=ret.annotation, description=ret.description, kind=ret.kind)
        for ret in schema.returns
    ]
    raises = [
        IRRaise(exception=exc.exception, description=exc.description)
        for exc in schema.raises
    ]
    return IRDocstring(
        symbol_id=symbol.qname,
        module=symbol.module,
        kind=symbol.kind,
        source_path=str(symbol.filepath),
        lineno=symbol.lineno,
        summary=schema.summary,
        extended=schema.extended,
        parameters=parameters,
        returns=returns,
        raises=raises,
        notes=list(schema.notes),
    )


def validate_ir(ir: IRDocstring) -> None:
    """Validate an :class:`IRDocstring` against simple invariants.

    Parameters
    ----------
    ir : IRDocstring
        IR docstring to validate.

    Raises
    ------
    ValueError
        If the IR version is unsupported, symbol_id is missing, kind is invalid,
        or parameter/return data is malformed.
    """
    if ir.ir_version != IR_VERSION:
        message = f"Unsupported IR version: {ir.ir_version}"
        raise ValueError(message)
    if not ir.symbol_id:
        message = "IR docstring must include a symbol identifier"
        raise ValueError(message)
    if ir.kind not in {"function", "method", "class"}:
        message = f"Unsupported symbol kind: {ir.kind}"
        raise ValueError(message)
    for parameter in ir.parameters:
        if not parameter.name:
            message = "Parameters must include a name"
            raise ValueError(message)
        if not parameter.kind:
            message = "Parameters must include a kind"
            raise ValueError(message)
    for ret in ir.returns:
        if ret.kind not in {"returns", "yields"}:
            message = f"Unsupported return kind: {ret.kind}"
            raise ValueError(message)


def serialize_ir(ir: IRDocstring) -> dict[str, object]:
    """Convert an :class:`IRDocstring` into a JSON-serialisable dictionary.

    Parameters
    ----------
    ir : IRDocstring
        IR docstring to serialize.

    Returns
    -------
    dict[str, object]
        JSON-serializable dictionary representation.
    """
    payload = cast("dict[str, object]", asdict(ir))
    payload["ir_version"] = ir.ir_version
    return payload


def generate_schema() -> dict[str, object]:
    """Return the JSON schema describing the docstring IR.

    Returns
    -------
    dict[str, object]
        JSON Schema 2020-12 dictionary describing the IR structure.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://kgfoundry.dev/schema/docstrings.json",
        "title": "KgFoundryDocstringIR",
        "type": "object",
        "required": [
            "ir_version",
            "symbol_id",
            "module",
            "kind",
            "source_path",
            "lineno",
            "summary",
            "parameters",
            "returns",
            "raises",
            "notes",
        ],
        "properties": {
            "ir_version": {"type": "string", "const": IR_VERSION},
            "symbol_id": {"type": "string"},
            "module": {"type": "string"},
            "kind": {"type": "string", "enum": ["function", "method", "class"]},
            "source_path": {"type": "string"},
            "lineno": {"type": "integer", "minimum": 1},
            "summary": {"type": "string"},
            "extended": {"type": ["string", "null"]},
            "parameters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "name",
                        "annotation",
                        "optional",
                        "default",
                        "description",
                        "kind",
                        "display_name",
                    ],
                    "properties": {
                        "name": {"type": "string"},
                        "annotation": {"type": ["string", "null"]},
                        "optional": {"type": "boolean"},
                        "default": {"type": ["string", "null"]},
                        "description": {"type": "string"},
                        "kind": {"type": "string"},
                        "display_name": {"type": ["string", "null"]},
                    },
                },
            },
            "returns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["annotation", "description", "kind"],
                    "properties": {
                        "annotation": {"type": ["string", "null"]},
                        "description": {"type": "string"},
                        "kind": {"type": "string", "enum": ["returns", "yields"]},
                    },
                },
            },
            "raises": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["exception", "description"],
                    "properties": {
                        "exception": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            },
            "notes": {"type": "array", "items": {"type": "string"}},
        },
    }


def write_schema(path: Path) -> None:
    """Write the IR JSON schema to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(generate_schema(), indent=2), encoding="utf-8")


__all__ = [
    "IR_VERSION",
    "IRDocstring",
    "IRParameter",
    "IRRaise",
    "IRReturn",
    "build_ir",
    "generate_schema",
    "serialize_ir",
    "validate_ir",
    "write_schema",
]
