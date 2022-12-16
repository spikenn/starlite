from dataclasses import dataclass, field, fields
from typing import Any, Optional

import pytest

from starlite.utils.dataclass import (
    dataclass_field_has_default_value,
    is_optional_dataclass_field,
)


@pytest.mark.parametrize(
    "field_type, expected",
    (
        (Optional[str], True),
        (Optional[int], True),
        (str, False),
        (int, False),
        (Any, True),
    ),
)
def test_is_optional_dataclass_field(field_type: Any, expected: bool) -> None:
    @dataclass
    class MyClass:
        field: field_type

    assert is_optional_dataclass_field(fields(MyClass)[0]) == expected


def test_dataclass_field_has_default_value() -> None:
    @dataclass
    class DataclassWithDefault:
        field: int = 1

    @dataclass
    class DataclassWithDefaultFactory:
        field: int = field(default_factory=lambda: 1)

    @dataclass
    class DataclassWithoutDefault:
        field: int

    assert dataclass_field_has_default_value(fields(DataclassWithDefault)[0]) is True
    assert dataclass_field_has_default_value(fields(DataclassWithDefaultFactory)[0]) is True
    assert dataclass_field_has_default_value(fields(DataclassWithoutDefault)[0]) is False
