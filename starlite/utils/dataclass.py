from dataclasses import MISSING, Field
from typing import Any


def is_optional_dataclass_field(field: "Field") -> bool:
    field_repr = repr(field.type)
    return field_repr.startswith("typing.Optional") or field_repr == "typing.Any"


def dataclass_field_has_default_value(field: "Field") -> bool:
    return field.default is not MISSING or field.default_factory is not MISSING


def get_dataclass_default_value(field: "Field") -> Any:
    if callable(field.default_factory):
        return field.default_factory()
    return field.default if field.default is not Ellipsis else None


def is_sequence_type_field(field: "Field") -> bool:
    return False
