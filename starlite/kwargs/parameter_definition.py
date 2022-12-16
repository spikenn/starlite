from dataclasses import MISSING
from types import MappingProxyType
from typing import Any, NamedTuple, Set

from starlite.constants import EXTRA_KEY_REQUIRED
from starlite.enums import ParamType


class ParameterDefinition(NamedTuple):
    """Tuple defining a kwarg representing a request parameter."""

    default_value: Any
    field_alias: str
    field_name: str
    is_required: bool
    is_sequence: bool
    param_type: ParamType


def create_parameter_definition(
    allow_none: bool,
    metadata: MappingProxyType,
    default_value: Any,
    field_name: str,
    path_parameters: Set[str],
    is_sequence: bool,
) -> ParameterDefinition:
    """Create a ParameterDefinition for the given pydantic FieldInfo instance and inserts it into the correct parameter
    set.

    Args:
        allow_none: Whether 'None' is an allowed value for the parameter.
        metadata: Dataclass field metadata.
        field_name: The field's name.
        default_value: The field's default value.
        path_parameters: A set of path parameter names.
        is_sequence: Whether the value of the parameter is a sequence.

    Returns:
        A ParameterDefinition tuple.
    """
    is_required = metadata.get(EXTRA_KEY_REQUIRED, True)
    default_value = default_value if default_value is not MISSING else None

    field_alias = metadata.get(ParamType.QUERY) or field_name
    param_type = ParamType.QUERY

    if field_name in path_parameters:
        field_alias = field_name
        param_type = ParamType.PATH
    elif metadata.get(ParamType.HEADER):
        field_alias = metadata[ParamType.HEADER]
        param_type = ParamType.HEADER
    elif metadata.get(ParamType.COOKIE):
        field_alias = metadata[ParamType.COOKIE]
        param_type = ParamType.COOKIE

    return ParameterDefinition(
        param_type=param_type,
        field_name=field_name,
        field_alias=field_alias,
        default_value=default_value,
        is_required=is_required and (default_value is None and not allow_none),
        is_sequence=is_sequence,
    )


def merge_parameter_sets(first: Set[ParameterDefinition], second: Set[ParameterDefinition]) -> Set[ParameterDefinition]:
    """Given two sets of parameter definitions, coming from different dependencies for example, merge them into a single
    set.
    """
    result: Set[ParameterDefinition] = first.intersection(second)
    difference = first.symmetric_difference(second)
    for param in difference:
        # add the param if it's either required or no-other param in difference is the same but required
        if param.is_required or not any(p.field_alias == param.field_alias and p.is_required for p in difference):
            result.add(param)
    return result
