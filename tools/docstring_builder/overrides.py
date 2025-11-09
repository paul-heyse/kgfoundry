"""Extended summary and type-override helpers for legacy docstring generation."""

from __future__ import annotations

DEFAULT_MAGIC_METHOD_FALLBACK = (
    "Special method customising Python's object protocol for this class. "
    "Use it to integrate with built-in operators, protocols, or runtime behaviours that expect "
    "instances to participate in the language's data model."
)

DEFAULT_PYDANTIC_ARTIFACT_SUMMARY = (
    "Support helper emitted by Pydantic model generation. "
    "The artefact exposes internal state used by the validation engine and is rarely invoked "
    "directly by application code."
)


def _format_magic_summary(lead: str) -> str:
    return (
        f"{lead}. "
        "This special method integrates the class with Python's data model so instances behave "
        "consistently with the language expectations."
    )


def _format_standard_summary(lead: str) -> str:
    return f"{lead}. Callers rely on this helper when working with the standard collection protocols."


def _format_pydantic_summary(lead: str) -> str:
    return (
        f"{lead}. "
        "The helper augments Pydantic's model runtime by exposing additional validation or export "
        "metadata."
    )


_MAGIC_METHOD_LEADS: dict[str, str] = {
    # Object lifecycle
    "__new__": "Construct a new instance before ``__init__`` runs",
    "__init__": "Initialise the instance with application specific state",
    "__init_subclass__": "Customise subclass creation hooks for this class hierarchy",
    "__del__": "Clean up resources when the instance is about to be destroyed",
    "__call__": "Invoke the instance as a callable to perform its core behaviour",
    # Attribute access
    "__getattr__": "Provide a fallback for unknown attribute lookups",
    "__getattribute__": "Intercept every attribute access on the instance",
    "__setattr__": "Control how attributes are assigned on the instance",
    "__delattr__": "Handle attribute deletion requests on behalf of the instance",
    "__dir__": "Expose the attributes reported when ``dir()`` is called on the instance",
    "__get__": "Implement the descriptor protocol for attribute access",
    "__set__": "Implement the descriptor protocol for attribute assignment",
    "__delete__": "Remove descriptor-managed attributes from the host instance",
    "__set_name__": "Receive the attribute name when the descriptor is bound on a class",
    # Pickling and copying
    "__getstate__": "Serialise the instance for pickling by returning state data",
    "__setstate__": "Restore state data during unpickling",
    "__reduce__": "Provide legacy pickling support by returning callable and arguments",
    "__reduce_ex__": "Provide protocol-aware pickling support for the instance",
    "__getnewargs__": "Supply positional constructor arguments during unpickling",
    "__getnewargs_ex__": "Supply both positional and keyword constructor arguments when restoring",
    "__copy__": "Produce a shallow copy of the instance",
    "__deepcopy__": "Produce a deep copy of the instance respecting nested references",
    # Numeric and comparison protocols
    "__add__": "Combine the instance with another value using addition semantics",
    "__sub__": "Subtract another value from the instance",
    "__mul__": "Multiply the instance with another value",
    "__matmul__": "Perform matrix multiplication with another operand",
    "__truediv__": "Divide the instance by another value using true division",
    "__floordiv__": "Divide the instance using floor division semantics",
    "__mod__": "Compute the modulus of the instance with another value",
    "__divmod__": "Support ``divmod`` by returning quotient and remainder",
    "__pow__": "Raise the instance to a power",
    "__lshift__": "Left-shift the instance by the provided offset",
    "__rshift__": "Right-shift the instance by the provided offset",
    "__and__": "Combine the instance with another value using bitwise AND",
    "__xor__": "Combine the instance with another value using bitwise XOR",
    "__or__": "Combine the instance with another value using bitwise OR",
    "__radd__": "Support reflected addition when the instance appears on the right-hand side",
    "__rsub__": "Support reflected subtraction for right-hand operands",
    "__rmul__": "Support reflected multiplication for right-hand operands",
    "__rmatmul__": "Support reflected matrix multiplication for right-hand operands",
    "__rtruediv__": "Support reflected true division for right-hand operands",
    "__rfloordiv__": "Support reflected floor division for right-hand operands",
    "__rmod__": "Support reflected modulo operations for right-hand operands",
    "__rdivmod__": "Support reflected ``divmod`` calls",
    "__rpow__": "Support reflected exponentiation when the instance is on the right",
    "__rlshift__": "Support reflected left shifts when the instance is on the right",
    "__rrshift__": "Support reflected right shifts when the instance is on the right",
    "__rand__": "Support reflected bitwise AND operations",
    "__rxor__": "Support reflected bitwise XOR operations",
    "__ror__": "Support reflected bitwise OR operations",
    "__iadd__": "Implement in-place addition for the instance",
    "__isub__": "Implement in-place subtraction for the instance",
    "__imul__": "Implement in-place multiplication for the instance",
    "__imatmul__": "Implement in-place matrix multiplication",
    "__itruediv__": "Implement in-place true division",
    "__ifloordiv__": "Implement in-place floor division",
    "__imod__": "Implement in-place modulo semantics",
    "__ipow__": "Implement in-place exponentiation",
    "__ilshift__": "Implement in-place left shift operations",
    "__irshift__": "Implement in-place right shift operations",
    "__iand__": "Implement in-place bitwise AND operations",
    "__ixor__": "Implement in-place bitwise XOR operations",
    "__ior__": "Implement in-place bitwise OR operations",
    "__neg__": "Return the arithmetic negation of the instance",
    "__pos__": "Return the arithmetic positive form of the instance",
    "__abs__": "Return the absolute value of the instance",
    "__invert__": "Return the bitwise inversion of the instance",
    "__lt__": "Compare the instance for ordering using less-than semantics",
    "__le__": "Compare the instance for ordering using less-than-or-equal semantics",
    "__eq__": "Compare the instance for equality",
    "__ne__": "Compare the instance for inequality",
    "__gt__": "Compare the instance for ordering using greater-than semantics",
    "__ge__": "Compare the instance for ordering using greater-than-or-equal semantics",
    # Container protocol
    "__len__": "Report how many items the instance contains",
    "__iter__": "Yield each element from the instance in iteration order",
    "__reversed__": "Iterate over the instance in reverse order",
    "__contains__": "Determine whether a candidate value is present in the instance",
    "__getitem__": "Retrieve an item from the instance by index or key",
    "__setitem__": "Assign a value within the instance by index or key",
    "__delitem__": "Remove an item from the instance by index or key",
    "__missing__": "Provide a fallback value when mapping lookups fail",
    "__length_hint__": "Estimate remaining items for sized iterables",
    # Type conversion
    "__int__": "Convert the instance to an integer representation",
    "__float__": "Convert the instance to a floating-point representation",
    "__complex__": "Convert the instance to a complex number representation",
    "__index__": "Provide an integer representation suitable for slicing",
    "__round__": "Round the instance to a given precision",
    "__trunc__": "Truncate the instance toward zero",
    "__floor__": "Round the instance down toward negative infinity",
    "__ceil__": "Round the instance up toward positive infinity",
    "__bytes__": "Convert the instance into raw ``bytes``",
    "__format__": "Produce a formatted string for the instance",
    "__sizeof__": "Report the in-memory size of the instance",
    "__fspath__": "Expose a filesystem path representation of the instance",
    "__buffer__": "Provide a writable buffer interface for the instance",
    "__release_buffer__": "Release a buffer exported by the instance",
    "__await__": "Support awaiting the instance for asynchronous integration",
    "__aenter__": "Enter an asynchronous context manager on behalf of the instance",
    "__aexit__": "Leave an asynchronous context manager on behalf of the instance",
    "__enter__": "Enter a context manager on behalf of the instance",
    "__exit__": "Leave a context manager on behalf of the instance",
    "__hash__": "Compute the hash value used by dictionaries and sets",
    "__bool__": "Determine the truthiness of the instance",
    "__class_getitem__": "Handle subscription on the class for generic aliases",
    "__instancecheck__": "Implement ``isinstance`` checks for virtual subclasses",
    "__subclasscheck__": "Implement ``issubclass`` checks for virtual subclasses",
    "__slots__": "Annotate slot definitions for instances of the class",
}

MAGIC_METHOD_EXTENDED_SUMMARIES: dict[str, str] = {
    name: _format_magic_summary(lead) for name, lead in _MAGIC_METHOD_LEADS.items()
}

_STANDARD_METHOD_LEADS: dict[str, str] = {
    "append": "Add a single item to the end of the collection",
    "clear": "Remove every entry from the container's internal storage",
    "copy": "Return a shallow copy of the collection",
    "extend": "Append each value from the supplied iterable",
    "insert": "Insert a value at the desired position within the collection",
    "pop": "Remove and return an item from the collection",
    "remove": "Delete the first matching value from the collection",
    "update": "Merge items from another mapping or iterable of pairs",
}

_STANDARD_METHOD_EXTENDED_SUMMARIES: dict[str, str] = {
    name: _format_standard_summary(lead)
    for name, lead in _STANDARD_METHOD_LEADS.items()
}

PYDANTIC_ARTIFACT_SUMMARIES: dict[str, str] = {
    "__pydantic_core_schema__": _format_pydantic_summary(
        "Return the compiled schema object used by the Pydantic validation engine"
    ),
    "__pydantic_core_config__": _format_pydantic_summary(
        "Expose the low level configuration state for the model"
    ),
    "__pydantic_decorators__": _format_pydantic_summary(
        "Provide access to decorators registered against the model"
    ),
    "__pydantic_extra__": _format_pydantic_summary(
        "Expose extra attributes captured when ``model_config['extra']`` allows them"
    ),
    "__pydantic_complete__": _format_pydantic_summary(
        "Indicate whether the model class has finished its post-processing lifecycle"
    ),
    "__pydantic_computed_fields__": _format_pydantic_summary(
        "Expose computed field definitions registered on the model"
    ),
    "__pydantic_fields_set__": _format_pydantic_summary(
        "Track the field names explicitly provided when initialising the model"
    ),
    "__pydantic_parent_namespace__": _format_pydantic_summary(
        "Expose the namespace used to resolve forward references during validation"
    ),
    "__pydantic_generic_metadata__": _format_pydantic_summary(
        "Expose metadata describing how the model behaves as a generic type"
    ),
    "__pydantic_model_complete__": _format_pydantic_summary(
        "Signal that the model class ran its completion hooks"
    ),
    "__pydantic_serializer__": _format_pydantic_summary(
        "Provide the compiled serializer callable for the model"
    ),
    "__pydantic_validator__": _format_pydantic_summary(
        "Provide the compiled validator callable for the model"
    ),
    "__pydantic_custom_init__": _format_pydantic_summary(
        "Flag whether the model defines a custom ``__init__`` implementation"
    ),
    "__pydantic_private__": _format_pydantic_summary(
        "Expose private attribute definitions declared on the model"
    ),
    "__pydantic_root_model__": _format_pydantic_summary(
        "Flag whether the model wraps a single root type instead of fields"
    ),
    "__pydantic_setattr_handlers__": _format_pydantic_summary(
        "Expose callbacks invoked when attributes are assigned on the model"
    ),
    "__pydantic_init_subclass__": _format_pydantic_summary(
        "Implement subclass hooks to maintain Pydantic metadata"
    ),
    "__pydantic_post_init__": _format_pydantic_summary(
        "Post-process initialisation values after ``__init__`` finishes"
    ),
    "__get_pydantic_core_schema__": _format_pydantic_summary(
        "Return or build the core schema used when exporting the model"
    ),
    "__get_pydantic_json_schema__": _format_pydantic_summary(
        "Return or build the JSON schema representation of the model"
    ),
    "model_config": _format_pydantic_summary(
        "Expose the ``ConfigDict`` controlling runtime behaviour for the model"
    ),
    "model_fields": _format_pydantic_summary(
        "Return the ordered mapping of field definitions declared on the model"
    ),
    "model_computed_fields": _format_pydantic_summary(
        "Expose the mapping of computed field definitions registered via decorators"
    ),
    "model_fields_set": _format_pydantic_summary(
        "Return the set of field names explicitly provided when instantiating the model"
    ),
    "model_extra": _format_pydantic_summary(
        "Access the mapping of extra attributes stored on the model instance"
    ),
    "model_post_init": _format_pydantic_summary(
        "Run the ``model_post_init`` hook that validates or transforms field values"
    ),
    "model_rebuild": _format_pydantic_summary(
        "Rebuild the model's schema and validators to reflect updated configuration"
    ),
    "model_parametrized_name": _format_pydantic_summary(
        "Generate a parameterised name for generic model specialisations"
    ),
    "model_dump": _format_pydantic_summary(
        "Serialise the model instance into a plain Python mapping"
    ),
    "model_dump_json": _format_pydantic_summary(
        "Serialise the model instance to a JSON document using compiled serializers"
    ),
    "model_validate": _format_pydantic_summary(
        "Validate arbitrary input data against the model schema"
    ),
    "model_validate_json": _format_pydantic_summary(
        "Validate JSON input by decoding and feeding it through the model schema"
    ),
    "model_copy": _format_pydantic_summary(
        "Create a shallow or deep copy of the model instance with optional updates"
    ),
    "model_construct": _format_pydantic_summary(
        "Construct a model instance without validation for trusted data sources"
    ),
    "model_serializer": _format_pydantic_summary(
        "Register a custom serializer for the model"
    ),
    "model_json_schema": _format_pydantic_summary(
        "Generate the JSON schema describing the model structure"
    ),
    "schema": _format_pydantic_summary(
        "Produce a dictionary describing the model's JSON schema"
    ),
    "schema_json": _format_pydantic_summary(
        "Serialise the model schema into JSON text"
    ),
    "dict": _format_pydantic_summary(
        "Serialise the model into a plain dictionary obeying configuration flags"
    ),
    "json": _format_pydantic_summary(
        "Serialise the model into JSON text obeying configuration flags"
    ),
    "copy": _format_pydantic_summary(
        "Create a copy of the model instance while optionally updating fields"
    ),
    "__private_attributes__": _format_pydantic_summary(
        "Expose the mapping of private attribute definitions declared on the model"
    ),
    "__class_vars__": _format_pydantic_summary(
        "Expose class variable definitions declared on the model"
    ),
    "__signature__": _format_pydantic_summary(
        "Expose the call signature presented by the model to type checkers"
    ),
}

QUALIFIED_NAME_OVERRIDES: dict[str, str] = {
    # NumPy scalars and aliases
    "numpy.float16": "numpy.float16",
    "numpy.float32": "numpy.float32",
    "numpy.float64": "numpy.float64",
    "numpy.int8": "numpy.int8",
    "numpy.int16": "numpy.int16",
    "numpy.int32": "numpy.int32",
    "numpy.int64": "numpy.int64",
    "numpy.uint8": "numpy.uint8",
    "numpy.uint16": "numpy.uint16",
    "numpy.uint32": "numpy.uint32",
    "numpy.uint64": "numpy.uint64",
    "np.float16": "numpy.float16",
    "np.float32": "numpy.float32",
    "np.float64": "numpy.float64",
    "np.int8": "numpy.int8",
    "np.int16": "numpy.int16",
    "np.int32": "numpy.int32",
    "np.int64": "numpy.int64",
    "np.uint8": "numpy.uint8",
    "np.uint16": "numpy.uint16",
    "np.uint32": "numpy.uint32",
    "np.uint64": "numpy.uint64",
    "ArrayLike": "numpy.typing.ArrayLike",
    "NDArray": "numpy.typing.NDArray",
    "numpy.dtype": "numpy.dtype",
    "numpy.typing.ArrayLike": "numpy.typing.ArrayLike",
    "numpy.typing.NDArray": "numpy.typing.NDArray",
    "np.dtype": "numpy.dtype",
    "np.ndarray": "numpy.ndarray",
    "np.typing.NDArray": "numpy.typing.NDArray",
    # PyArrow core types
    "pyarrow.Array": "pyarrow.Array",
    "pyarrow.DataType": "pyarrow.DataType",
    "pyarrow.Field": "pyarrow.Field",
    "pyarrow.Int64Type": "pyarrow.Int64Type",
    "pyarrow.RecordBatch": "pyarrow.RecordBatch",
    "pyarrow.Schema": "pyarrow.Schema",
    "pyarrow.schema": "pyarrow.schema",
    "pyarrow.StringType": "pyarrow.StringType",
    "pyarrow.Table": "pyarrow.Table",
    "pyarrow.TimestampType": "pyarrow.TimestampType",
    # Pydantic helpers
    "pydantic.AliasChoices": "pydantic.AliasChoices",
    "pydantic.ConfigDict": "pydantic.ConfigDict",
    "pydantic.Field": "pydantic.Field",
    "pydantic.TypeAdapter": "pydantic.TypeAdapter",
    "pydantic.ValidationError": "pydantic.ValidationError",
    "pydantic.field_validator": "pydantic.field_validator",
    "pydantic.fields.Field": "pydantic.fields.Field",
    "pydantic.model_validator": "pydantic.model_validator",
    # typing extensions
    "typing_extensions.Annotated": "typing_extensions.Annotated",
    "typing_extensions.NotRequired": "typing_extensions.NotRequired",
    "typing_extensions.Self": "typing_extensions.Self",
    "typing_extensions.TypeAlias": "typing_extensions.TypeAlias",
    "typing_extensions.TypedDict": "typing_extensions.TypedDict",
    # Standard library favourites
    "collections.Counter": "collections.Counter",
    "collections.defaultdict": "collections.defaultdict",
    "collections.deque": "collections.deque",
    "collections.OrderedDict": "collections.OrderedDict",
    "datetime.datetime": "datetime.datetime",
    "datetime.timedelta": "datetime.timedelta",
    "pathlib.Path": "pathlib.Path",
    "uuid.UUID": "uuid.UUID",
    # Project specific overrides
    "FloatArray": "src.vectorstore_faiss.gpu.FloatArray",
    "IntArray": "src.vectorstore_faiss.gpu.IntArray",
    "StrArray": "src.vectorstore_faiss.gpu.StrArray",
    "VecArray": "src.search_api.faiss_adapter.VecArray",
    "Doc": "src.kgfoundry_common.models.Doc",
    "Chunk": "src.kgfoundry_common.models.Chunk",
    "Concept": "src.ontology.catalog.Concept",
    "DownloadError": "src.kgfoundry_common.errors.DownloadError",
    "UnsupportedMIMEError": "src.kgfoundry_common.errors.UnsupportedMIMEError",
    # Additional scientific stack entries to exceed 100 total
    "pandas.DataFrame": "pandas.DataFrame",
    "pandas.Series": "pandas.Series",
    "pandas.Index": "pandas.Index",
    "pandas.Timestamp": "pandas.Timestamp",
    "scipy.sparse.csr_matrix": "scipy.sparse.csr_matrix",
    "scipy.sparse.csc_matrix": "scipy.sparse.csc_matrix",
    "scipy.interpolate.UnivariateSpline": "scipy.interpolate.UnivariateSpline",
    "scipy.optimize.OptimizeResult": "scipy.optimize.OptimizeResult",
    "httpx.Client": "httpx.Client",
    "httpx.Response": "httpx.Response",
    "httpx.Request": "httpx.Request",
    "pytest.Config": "pytest.Config",
    "pytest.MonkeyPatch": "pytest.MonkeyPatch",
    "pluggy.HookimplMarker": "pluggy.HookimplMarker",
    "typing.Iterable": "collections.abc.Iterable",
    "typing.Mapping": "collections.abc.Mapping",
    "typing.MutableMapping": "collections.abc.MutableMapping",
    "typing.MutableSequence": "collections.abc.MutableSequence",
    "typing.MutableSet": "collections.abc.MutableSet",
    "typing.Sequence": "collections.abc.Sequence",
    "typing.Collection": "collections.abc.Collection",
    "typing.Reversible": "collections.abc.Reversible",
    "typing.SupportsFloat": "typing.SupportsFloat",
    "typing.SupportsInt": "typing.SupportsInt",
    "typing.SupportsComplex": "typing.SupportsComplex",
    "typing.SupportsBytes": "typing.SupportsBytes",
    "typing.SupportsRound": "typing.SupportsRound",
    "typing.Hashable": "collections.abc.Hashable",
    "typing.Callable": "collections.abc.Callable",
    "typing.Generator": "collections.abc.Generator",
    "typing.AsyncGenerator": "collections.abc.AsyncGenerator",
    "typing.Iterator": "collections.abc.Iterator",
    "typing.AsyncIterator": "collections.abc.AsyncIterator",
    "typing.Coroutine": "collections.abc.Coroutine",
    "typing.Awaitable": "collections.abc.Awaitable",
    "typing.AsyncIterable": "collections.abc.AsyncIterable",
    "typing.ContextManager": "contextlib.AbstractContextManager",
    "typing.AsyncContextManager": "contextlib.AbstractAsyncContextManager",
    "typing.Protocol": "typing.Protocol",
    "typing.TypeGuard": "typing.TypeGuard",
    "typing.TypeVar": "typing.TypeVar",
    "typing.Literal": "typing.Literal",
    "typing.Final": "typing.Final",
    "typing.ClassVar": "typing.ClassVar",
    "typing.Optional": "typing.Optional",
    "typing.Union": "typing.Union",
    "typing.Any": "typing.Any",
}


def _is_magic(name: str) -> bool:
    """Return True when ``name`` matches a known Python magic method.

    Parameters
    ----------
    name : str
        Method name to check.

    Returns
    -------
    bool
        True if name is a known magic method, False otherwise.
    """
    return name in MAGIC_METHOD_EXTENDED_SUMMARIES


def _is_pydantic_artifact(name: str) -> bool:
    """Return True when ``name`` refers to a Pydantic-specific helper.

    Parameters
    ----------
    name : str
        Method name to check.

    Returns
    -------
    bool
        True if name is a Pydantic artifact, False otherwise.
    """
    return name in PYDANTIC_ARTIFACT_SUMMARIES or name.startswith("__pydantic")


def summarize(name: str, kind: str) -> str:
    """Return a concise summary sentence for a symbol.

    Parameters
    ----------
    name : str
        Symbol name.
    kind : str
        Symbol kind (e.g., "class", "function", "module", "attribute").

    Returns
    -------
    str
        Summary sentence template for the symbol.
    """
    cleaned = name or "object"
    if kind == "class":
        return f"Describe the ``{cleaned}`` class."
    if kind == "module":
        return f"Summarise the ``{cleaned}`` module."
    if kind == "attribute":
        return f"Describe the ``{cleaned}`` attribute."
    return f"Describe the ``{cleaned}`` callable."


def extended_summary(
    kind: str, name: str, module: str, node: object | None = None
) -> str:
    """Return the extended summary paragraph for the symbol.

    Parameters
    ----------
    kind : str
        Symbol kind (e.g., "function", "class", "module").
    name : str
        Symbol name.
    module : str
        Module name (unused, kept for signature compatibility).
    node : object | None, optional
        AST node for additional context (used for class detection).

    Returns
    -------
    str
        Extended summary paragraph text.
    """
    del module
    if kind == "function":
        summary = _function_extended_summary(name)
        return summary or DEFAULT_MAGIC_METHOD_FALLBACK
    if kind == "class":
        return _class_extended_summary(node)
    if kind == "module":
        return (
            "Explain the module's responsibilities and how it interacts with neighbouring "
            "components. Provide additional context so readers understand the module's role in "
            "the documentation pipeline."
        )
    return DEFAULT_MAGIC_METHOD_FALLBACK


def _function_extended_summary(name: str) -> str | None:
    if _is_magic(name):
        return MAGIC_METHOD_EXTENDED_SUMMARIES[name]
    if name in _STANDARD_METHOD_EXTENDED_SUMMARIES:
        return _STANDARD_METHOD_EXTENDED_SUMMARIES[name]
    if _is_pydantic_artifact(name):
        return PYDANTIC_ARTIFACT_SUMMARIES.get(name, DEFAULT_PYDANTIC_ARTIFACT_SUMMARY)
    return None


def _class_extended_summary(node: object | None) -> str:
    if hasattr(node, "bases"):
        for base in getattr(node, "bases", []):
            target = getattr(base, "id", "") or getattr(
                getattr(base, "attr", None), "value", ""
            )
            if target == "BaseModel" or getattr(base, "attr", "") == "BaseModel":
                return (
                    "Describe the Pydantic model and the behaviour it provides to callers. "
                    "Callers interact with validated data through this model."
                )
    return (
        "Describe the data structure and how instances collaborate with the surrounding "
        "package. Highlight how the class supports nearby modules to guide readers through "
        "the codebase."
    )


__all__ = [
    "DEFAULT_MAGIC_METHOD_FALLBACK",
    "DEFAULT_PYDANTIC_ARTIFACT_SUMMARY",
    "MAGIC_METHOD_EXTENDED_SUMMARIES",
    "PYDANTIC_ARTIFACT_SUMMARIES",
    "QUALIFIED_NAME_OVERRIDES",
    "_is_magic",
    "_is_pydantic_artifact",
    "extended_summary",
    "summarize",
]
