"""Normalize harvested docstrings to mirror runtime signatures."""

from __future__ import annotations

import inspect
import textwrap
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from tools.docstring_builder.models import DocstringBuilderError
from tools.docstring_builder.normalizer_annotations import format_annotation
from tools.docstring_builder.normalizer_signature import (
    load_module_globals,
    resolve_callable,
    signature_and_hints,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from tools.docstring_builder.harvest import SymbolHarvest


@dataclass(slots=True, frozen=True)
class _Section:
    title: str | None
    content: list[str]


@dataclass(slots=True, frozen=True)
class _ParameterBlock:
    display_name: str
    description: list[str]


@dataclass(slots=True, frozen=True)
class _ReturnBlock:
    description: list[str]


def _parse_sections(docstring: str) -> list[_Section]:
    lines = docstring.splitlines()
    sections: list[_Section] = []
    current = _Section(title=None, content=[])
    i = 0
    while i < len(lines):
        line = lines[i]
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        underline = next_line.strip()
        if (
            line.strip()
            and not line.startswith(" ")
            and underline
            and set(underline) == {"-"}
            and len(underline) >= len(line.strip())
        ):
            sections.append(current)
            current = _Section(title=line.strip(), content=[])
            i += 2
            continue
        current.content.append(line)
        i += 1
    sections.append(current)
    return sections


def _join_sections(sections: list[_Section]) -> str:
    output: list[str] = []
    for section in sections:
        if section.title is not None:
            if output and output[-1]:
                output.append("")
            output.append(section.title)
            output.append("-" * len(section.title))
        output.extend(section.content)
    return "\n".join(output).strip()


def _relayout_marker_block(docstring: str, marker: str) -> str:
    """Ensure the ownership marker sits on its own paragraph.

    Parameters
    ----------
    docstring : str
        Original docstring text.
    marker : str
        Ownership marker string to relocate.

    Returns
    -------
    str
        Docstring with marker relocated to its own paragraph.
    """
    if not marker:
        return docstring

    lines = docstring.splitlines()
    if not lines:
        return marker

    summary = lines[0].replace(marker, "").strip()
    remaining = [line for line in lines[1:] if marker not in line]

    while remaining and not remaining[0].strip():
        remaining.pop(0)
    while remaining and not remaining[-1].strip():
        remaining.pop()

    if summary and summary[-1] not in ".!?":
        summary = summary.rstrip(".!? ") + "."

    parts: list[str] = []
    if summary:
        parts.append(summary)
    else:
        parts.append("")

    parts.append("")
    parts.append(marker)

    if remaining:
        parts.append("")
        parts.extend(remaining)

    return "\n".join(parts).strip()


def _parse_parameters(section: _Section) -> dict[str, _ParameterBlock]:
    entries: dict[str, _ParameterBlock] = {}
    lines = section.content
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        name_part, _meta = line.split(":", 1)
        display_name = name_part.strip()
        canonical = display_name.lstrip("*")
        desc: list[str] = []
        i += 1
        while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
            desc.append(lines[i])
            i += 1
        entries[canonical] = _ParameterBlock(
            display_name=display_name, description=desc
        )
    return entries


def _parse_returns(section: _Section) -> _ReturnBlock:
    lines = section.content
    if not lines:
        return _ReturnBlock(description=[])
    desc = list(lines[1:])
    return _ReturnBlock(description=desc)


def _ensure_description(description: list[str], fallback: str) -> list[str]:
    if description:
        normalised: list[str] = []
        has_text = False
        for line in description:
            stripped = line.strip()
            if not stripped:
                continue
            has_text = True
            if not line.startswith("    "):
                normalised.append(f"    {stripped}")
            else:
                normalised.append(line.rstrip())
        if has_text:
            return normalised
    return [f"    {fallback}"]


def _merge_default(description: list[str], default: str | None) -> list[str]:
    if not default:
        return description
    merged: list[str] = []
    added = False
    seen_defaults = False
    for line in description:
        stripped = line.strip()
        marker = f"Defaults to ``{default}``."
        if stripped.startswith(f"Optional parameter default ``{default}``."):
            added = True
            tail = stripped.removeprefix(
                f"Optional parameter default ``{default}``."
            ).strip()
            merged.append(f"    Defaults to ``{default}``.")
            if tail:
                merged.append(f"    {tail}")
            continue
        if stripped == marker:
            if not seen_defaults:
                merged.append("    " + marker)
                seen_defaults = True
            added = True
            continue
        merged.append(line)
    if not added:
        merged.append(f"    Defaults to ``{default}``.")
    return merged


def _build_parameters_content(
    signature: inspect.Signature,
    hints: dict[str, object],
    section: _Section | None,
    module_globals: Mapping[str, object],
    symbol: SymbolHarvest,
) -> list[str]:
    blocks: dict[str, _ParameterBlock] = _parse_parameters(section) if section else {}
    harvested: dict[str, str | None] = {
        param.name: param.annotation for param in symbol.parameters
    }
    lines: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            display = f"*{parameter.name}"
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            display = f"**{parameter.name}"
        else:
            display = parameter.name
        annotation = hints.get(parameter.name, parameter.annotation)
        annotation_text = format_annotation(annotation, module_globals)
        if annotation_text is None:
            harvested_text = harvested.get(parameter.name)
            annotation_text = harvested_text or "Any"
        optional = parameter.default is not inspect.Signature.empty
        default_text = _format_default(parameter.default)
        block = blocks.get(parameter.name) or _ParameterBlock(
            display_name=display,
            description=[],
        )
        desc_lines = _ensure_description(
            block.description, f"Describe ``{parameter.name}``."
        )
        if optional and default_text:
            desc_lines = _merge_default(desc_lines, default_text)
        signature_line = f"{display} : {annotation_text}"
        if optional:
            signature_line += ", optional"
        lines.append(signature_line)
        lines.extend(desc_lines)
    return lines


def _build_returns_content(
    signature: inspect.Signature,
    hints: dict[str, object],
    section: _Section | None,
    module_globals: Mapping[str, object],
) -> list[str]:
    annotation = hints.get("return", signature.return_annotation)
    annotation_text = format_annotation(annotation, module_globals)
    if annotation_text is None or annotation_text == "None":
        return []
    block = _parse_returns(section) if section else _ReturnBlock(description=[])
    desc_lines = _ensure_description(block.description, "Describe return value.")
    return [annotation_text, *desc_lines]


def _format_default(value: object) -> str | None:
    if value is inspect.Signature.empty:
        return None
    if isinstance(value, str):
        return repr(value)
    if value is Ellipsis:
        return "..."
    return repr(value)


def _update_parameter_section(
    sections: list[_Section], parameter_section: _Section | None, content: list[str]
) -> None:
    if parameter_section and content:
        idx = sections.index(parameter_section)
        sections[idx] = replace(parameter_section, content=content)
        return
    if parameter_section and not content:
        sections.remove(parameter_section)
        return
    if not parameter_section and content:
        insertion_index = 1 if sections and sections[0].title is None else 0
        sections.insert(insertion_index, _Section(title="Parameters", content=content))


def _update_return_section(
    sections: list[_Section],
    return_section: _Section | None,
    content: list[str],
    section_title: str,
) -> None:
    if return_section and content:
        idx = sections.index(return_section)
        sections[idx] = replace(return_section, content=content)
        return
    if return_section and not content:
        sections.remove(return_section)
        return
    if not return_section and content:
        sections.append(_Section(title=section_title, content=content))


def normalize_docstring(symbol: SymbolHarvest, marker: str) -> str | None:
    """Return a docstring updated to mirror runtime annotations.

    Parameters
    ----------
    symbol : SymbolHarvest
        Symbol metadata including docstring and signature information.
    marker : str
        Ownership marker string.

    Returns
    -------
    str | None
        Normalized docstring if symbol has a docstring and can be resolved, None otherwise.
    """
    if not symbol.docstring:
        return None
    original = textwrap.dedent(symbol.docstring).strip()
    try:
        callable_obj = resolve_callable(symbol)
        module_globals = load_module_globals(symbol.module)
        signature, hints = signature_and_hints(callable_obj, module_globals)
    except DocstringBuilderError:
        return None

    body = original
    sections = _parse_sections(body)
    parameter_section = next(
        (section for section in sections if section.title == "Parameters"), None
    )
    return_section_title = "Yields" if symbol.is_generator else "Returns"
    return_section = next(
        (section for section in sections if section.title == return_section_title), None
    )

    parameter_content = _build_parameters_content(
        signature, hints, parameter_section, module_globals, symbol
    )
    return_content = _build_returns_content(
        signature, hints, return_section, module_globals
    )

    _update_parameter_section(sections, parameter_section, parameter_content)
    _update_return_section(
        sections, return_section, return_content, return_section_title
    )

    updated = _join_sections(sections)
    if marker:
        updated = _relayout_marker_block(updated, marker)
    return updated


__all__ = ["normalize_docstring"]
