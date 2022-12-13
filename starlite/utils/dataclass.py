from dataclasses import Field, MISSING


def is_optional_dataclass_field(field: "Field") -> bool:
    field_repr = repr(field.type)
    return field_repr.startswith("typing.Optional") or field_repr == "typing.Any"


def dataclass_field_has_default_value(field: "Field") -> bool:
    return field.default is not MISSING or field.default_factory is not MISSING
