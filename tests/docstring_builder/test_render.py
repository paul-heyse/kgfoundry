"""Tests for docstring rendering utilities."""

from pathlib import Path

from tools.docstring_builder.render import render_docstring, write_template_to
from tools.docstring_builder.schema import DocstringSchema, ParameterDoc


def test_render_signature_includes_none_default() -> None:
    """Parameters defaulting to ``None`` should surface in the signature."""
    parameter = ParameterDoc(
        name="value",
        annotation="int | None",
        description="Describe the value.",
        optional=True,
        default="None",
        display_name="value",
        kind="positional_or_keyword",
    )
    schema = DocstringSchema(summary="Summarize value.", parameters=[parameter])

    docstring = render_docstring(schema, marker="<!-- marker -->", include_signature=True)

    assert "= None" in docstring


def test_render_docstring_preserves_special_characters() -> None:
    """Docstring rendering should not HTML-escape schema content."""
    schema = DocstringSchema(summary="Return <value> 'untouched'.")
    rendered = render_docstring(schema=schema, marker="[generated]")

    assert "<value>" in rendered
    assert "'untouched'" in rendered


def test_render_docstring_includes_falsey_default() -> None:
    """Docstring parameter sections must include empty-string defaults."""
    parameter = ParameterDoc(
        name="title",
        annotation="str",
        description="Title for the resource.",
        optional=True,
        default="",
    )
    schema = DocstringSchema(summary="Return a title.", parameters=[parameter])

    rendered = render_docstring(schema=schema, marker="[generated]")

    assert ', by default ""' in rendered


def test_render_signature_includes_empty_string_default() -> None:
    """Signature rendering should quote empty-string defaults."""
    parameter = ParameterDoc(
        name="title",
        annotation="str",
        description="Title for the resource.",
        optional=True,
        default="",
        kind="positional_or_keyword",
    )
    schema = DocstringSchema(summary="Return a title.", parameters=[parameter])

    rendered = render_docstring(schema=schema, marker="[generated]", include_signature=True)

    assert '= ""' in rendered


def test_write_template_to_creates_parent_directories(tmp_path: Path) -> None:
    """Persisting the template should succeed even for nested destinations."""
    destination = tmp_path / "nested" / "template.jinja"

    write_template_to(destination)

    assert destination.exists()
    contents = destination.read_text(encoding="utf-8")
    assert "{{ schema.summary }}" in contents
