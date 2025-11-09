"""Public facade exposing typed tooling dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools._types.pytestarch_facade import (
    EvaluableArchitectureProtocol,
    LayeredArchitectureProtocol,
    ModuleNameFilterProtocol,
    get_evaluable_architecture_fn,
    get_evaluable_architecture_for_module_objects_fn,
    get_layered_architecture_cls,
    get_layered_architecture_factory,
    get_module_name_filter_cls,
    get_module_name_filter_factory,
)

if TYPE_CHECKING:
    from collections.abc import Callable

LayeredArchitecture: type[LayeredArchitectureProtocol] = get_layered_architecture_cls()
ModuleNameFilter: type[ModuleNameFilterProtocol] = get_module_name_filter_cls()
get_evaluable_architecture: Callable[..., EvaluableArchitectureProtocol] = (
    get_evaluable_architecture_fn()
)
get_evaluable_architecture_for_module_objects: Callable[
    ..., EvaluableArchitectureProtocol
] = get_evaluable_architecture_for_module_objects_fn()

EvaluableArchitecture = EvaluableArchitectureProtocol


new_layered_architecture = get_layered_architecture_factory()
new_module_name_filter = get_module_name_filter_factory()

__all__ = [
    "EvaluableArchitecture",
    "EvaluableArchitectureProtocol",
    "LayeredArchitecture",
    "LayeredArchitectureProtocol",
    "ModuleNameFilter",
    "ModuleNameFilterProtocol",
    "get_evaluable_architecture",
    "get_evaluable_architecture_for_module_objects",
    "new_layered_architecture",
    "new_module_name_filter",
]
