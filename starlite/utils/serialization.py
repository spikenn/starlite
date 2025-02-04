from collections import deque
from decimal import Decimal
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)
from pathlib import PurePosixPath
from re import Pattern
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Union

import msgspec
from pydantic import (
    BaseModel,
    ByteSize,
    ConstrainedBytes,
    ConstrainedDate,
    NameEmail,
    SecretField,
    StrictBool,
)
from pydantic.color import Color
from pydantic.json import decimal_encoder

if TYPE_CHECKING:
    from starlite.types import TypeEncodersMap

DEFAULT_TYPE_ENCODERS: "TypeEncodersMap" = {
    PurePosixPath: str,
    # pydantic specific types
    BaseModel: lambda m: m.dict(),
    ByteSize: lambda b: b.real,
    NameEmail: str,
    Color: str,
    SecretField: str,
    ConstrainedBytes: lambda b: b.decode("utf-8"),
    ConstrainedDate: lambda d: d.isoformat(),
    IPv4Address: str,
    IPv4Interface: str,
    IPv4Network: str,
    IPv6Address: str,
    IPv6Interface: str,
    IPv6Network: str,
    # pydantic compatibility
    deque: list,
    Decimal: decimal_encoder,
    StrictBool: int,
    Pattern: lambda o: o.pattern,
    # support subclasses of stdlib types, If no previous type matched, these will be
    # the last type in the mro, so we use this to (attempt to) convert a subclass into
    # its base class. # see https://github.com/jcrist/msgspec/issues/248
    # and https://github.com/starlite-api/starlite/issues/1003
    str: str,
    int: int,
    float: float,
    set: set,
    frozenset: frozenset,
}


def default_serializer(value: Any, type_encoders: Optional[Dict[Any, Callable[[Any], Any]]] = None) -> Any:
    """Transform values non-natively supported by `msgspec`

    Args:
        value: A value to serialize#
        type_encoders: Mapping of types to callables to transforming types
    Returns:
        A serialized value
    Raises:
        TypeError: if value is not supported
    """
    if type_encoders is None:
        type_encoders = DEFAULT_TYPE_ENCODERS
    for base in value.__class__.__mro__[:-1]:
        try:
            encoder = type_encoders[base]
        except KeyError:
            continue
        return encoder(value)
    raise TypeError(f"Unsupported type: {type(value)!r}")


def dec_hook(type_: Any, value: Any) -> Any:  # pragma: no cover
    """Transform values non-natively supported by `msgspec`

    Args:
        type_: Encountered type
        value: Value to coerce

    Returns:
        A `msgspec`-supported type
    """
    if issubclass(type_, BaseModel):
        return type_(**value)
    raise TypeError(f"Unsupported type: {type(value)!r}")


_msgspec_json_encoder = msgspec.json.Encoder(enc_hook=default_serializer)
_msgspec_json_decoder = msgspec.json.Decoder(dec_hook=dec_hook)
_msgspec_msgpack_encoder = msgspec.msgpack.Encoder(enc_hook=default_serializer)
_msgspec_msgpack_decoder = msgspec.msgpack.Decoder(dec_hook=dec_hook)


def encode_json(obj: Any, default: Optional[Callable[[Any], Any]] = default_serializer) -> bytes:
    """Encode a value into JSON.

    Args:
        obj: Value to encode
        default: Optional callable to support non-natively supported types.

    Returns:
        JSON as bytes
    """
    if default is None or default is default_serializer:
        return _msgspec_json_encoder.encode(obj)
    return msgspec.json.encode(obj, enc_hook=default)


def decode_json(raw: Union[str, bytes]) -> Any:
    """Decode a JSON string/bytes into an object.

    Args:
        raw: Value to decode

    Returns:
        An object
    """
    return _msgspec_json_decoder.decode(raw)


def encode_msgpack(obj: Any, enc_hook: Optional[Callable[[Any], Any]] = default_serializer) -> bytes:
    """Encode a value into MessagePack.

    Args:
        obj: Value to encode
        enc_hook: Optional callable to support non-natively supported types

    Returns:
        MessagePack as bytes
    """
    if enc_hook is None or enc_hook is default_serializer:
        return _msgspec_msgpack_encoder.encode(obj)
    return msgspec.msgpack.encode(obj, enc_hook=enc_hook)


def decode_msgpack(raw: bytes) -> Any:
    """Decode a MessagePack string/bytes into an object.

    Args:
        raw: Value to decode

    Returns:
        An object
    """
    return _msgspec_msgpack_decoder.decode(raw)
