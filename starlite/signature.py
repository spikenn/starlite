from dataclasses import MISSING
from dataclasses import Field as DataclassField
from dataclasses import fields as get_dataclass_fields
from dataclasses import make_dataclass
from inspect import Parameter, Signature
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    Generator,
    List,
    Set,
    Tuple,
    Type,
    Union,
    cast,
)

from pydantic_factories import ModelFactory
from typing_extensions import get_args

from starlite.connection import Request
from starlite.enums import ScopeType
from starlite.exceptions import (
    ImproperlyConfiguredException,
    InternalServerException,
    ValidationException,
)
from starlite.plugins.base import PluginMapping, PluginProtocol, get_plugin_for_value
from starlite.utils import (
    is_dependency_field,
    is_optional_union,
    should_skip_dependency_validation,
)
from starlite.utils.helpers import unwrap_partial

if TYPE_CHECKING:
    from pydantic.error_wrappers import ErrorDict

    from starlite import ASGIConnection
    from starlite.datastructures import URL
    from starlite.types import AnyCallable


SKIP_NAMES = {"self", "cls"}


class SignatureModel:
    """Dataclass representing a function's signature."""

    __slots__ = ("dependency_name_set", "field_plugin_mappings", "return_annotation", "dataclass_fields")

    dependency_name_set: ClassVar[Set[str]]
    field_plugin_mappings: ClassVar[Dict[str, PluginMapping]]
    return_annotation: ClassVar[Any]
    dataclass_fields: ClassVar[Tuple[DataclassField, ...]]

    @classmethod
    def parse_values_from_connection_kwargs(cls, connection: "ASGIConnection", **kwargs: Any) -> Dict[str, Any]:
        """Given a dictionary of values extracted from the connection, create an instance of the given SignatureModel
        subclass and return the parsed values.

        This is not equivalent to calling the '.dict'  method of the pydantic model, because it doesn't convert nested
        values into dictionary, just extracts the data from the signature model
        """
        signature = cls(**kwargs)
        if signature.field_plugin_mappings:
            return {field.name: signature.resolve_field_value(field.name) for field in cls.dataclass_fields}
        return {
            field.name: getattr(signature, field.name)  # pylint: disable=unnecessary-dunder-call
            for field in cls.dataclass_fields
        }

    def resolve_field_value(self, field_name: str) -> Any:
        """Given a field key, return value using plugin mapping, if available."""
        value = self.__getattribute__(field_name)  # pylint: disable=unnecessary-dunder-call
        mapping = self.field_plugin_mappings.get(field_name)
        return mapping.get_model_instance_for_value(value) if mapping else value

    @classmethod
    def construct_exception(
        cls, connection: "ASGIConnection", exc: Exception
    ) -> Union[InternalServerException, ValidationException]:
        """Distinguish between validation errors that arise from parameters and dependencies.

        If both parameter and dependency values are invalid, we raise the client error first.

        Args:
            connection: A Request or WebSocket
            exc: A ValidationError

        Returns:
            A ValidationException or InternalServerException
        """
        server_errors: List["ErrorDict"] = []
        client_errors: List["ErrorDict"] = []

        for error in exc.errors():
            if cls.is_server_error(error):
                server_errors.append(error)
            else:
                client_errors.append(error)

        method, url = cls.get_connection_method_and_url(connection)

        if client_errors:
            return ValidationException(detail=f"Validation failed for {method} {url}", extra=client_errors)

        return InternalServerException(detail=f"A dependency failed validation for {method} {url}", extra=server_errors)

    @classmethod
    def is_server_error(cls, error: "ErrorDict") -> bool:
        """Check whether given validation error is a server error."""
        return error["loc"][-1] in cls.dependency_name_set

    @staticmethod
    def get_connection_method_and_url(connection: "ASGIConnection") -> Tuple[str, "URL"]:
        """Extract method and URL from Request or WebSocket."""
        method = connection.method if isinstance(connection, Request) else ScopeType.WEBSOCKET
        return method, connection.url


class SignatureParameter:
    """Represents the parameters of a callable for purpose of signature model generation."""

    __slots__ = (
        "annotation",
        "default",
        "name",
        "optional",
    )

    annotation: Any
    default: Any
    name: str
    optional: bool

    def __init__(self, fn_name: str, parameter_name: str, parameter: Parameter) -> None:
        """Initialize SignatureParameter.

        Args:
            fn_name: Name of function.
            parameter_name: Name of parameter.
            parameter: inspect.Parameter
        """
        if parameter.annotation in {Signature.empty, MISSING}:
            raise ImproperlyConfiguredException(
                f"Kwarg {parameter_name} of {fn_name} does not have a type annotation. If it "
                f"should receive any value, use the 'Any' type."
            )
        self.annotation = parameter.annotation
        self.default = parameter.default
        self.name = parameter_name
        self.optional = is_optional_union(parameter.annotation)


class SignatureModelFactory:
    """Utility class for constructing the signature model and grouping associated state.

    Instance available at `SignatureModel.factory`.

    The following attributes are populated after the `model()` method has been called to generate
    the `SignatureModel` subclass.

    Attributes:
        field_plugin_mappings: Maps parameter name, to `PluginMapping` where a plugin has been applied.
        field_definitions:  Maps parameter name to the `(<type>, <default>)` tuple passed to `pydantic.create_model()`.
        defaults: Maps parameter name to default value, if one defined.
        dependency_name_set: The names of all known dependency parameters.
    """

    __slots__ = (
        "defaults",
        "dependency_name_set",
        "field_definitions",
        "field_plugin_mappings",
        "fn_module_name",
        "fn_name",
        "plugins",
        "signature",
    )

    def __init__(self, fn: "AnyCallable", plugins: List["PluginProtocol"], dependency_names: Set[str]) -> None:
        """Initialise `SignatureModelFactory`

        Args:
            fn: A callable
            plugins: A list of plugins
            dependency_names: Dependency names
        """
        if fn is None:
            raise ImproperlyConfiguredException("Parameter `fn` to `SignatureModelFactory` cannot be `None`.")

        fn = unwrap_partial(fn)
        self.signature = Signature.from_callable(fn)
        self.fn_name = getattr(fn, "__name__", "anonymous")
        self.fn_module_name = getattr(fn, "__module__", None)
        self.plugins = plugins
        self.field_plugin_mappings: Dict[str, PluginMapping] = {}
        self.field_definitions: Dict[str, Any] = {}
        self.defaults: Dict[str, Any] = {}
        self.dependency_name_set = dependency_names

    def check_for_unprovided_dependency(self, parameter: SignatureParameter) -> None:
        """Where a dependency has been explicitly marked using the `Dependency` function, it is a configuration error if
        that dependency has been defined without a default value, and it hasn't been provided to the handler.

        Args:
            parameter  SignatureParameter

        Raises:
            `ImproperlyConfiguredException`
        """
        if parameter.optional:
            return
        if not is_dependency_field(parameter.default):
            return
        if parameter.default is not MISSING:
            return
        if parameter.name not in self.dependency_name_set:
            raise ImproperlyConfiguredException(
                f"Explicit dependency '{parameter.name}' for '{self.fn_name}' has no default value, "
                f"or provided dependency."
            )

    def collect_dependency_names(self, parameter: SignatureParameter) -> None:
        """Add parameter name of dependencies declared using `Dependency()` function to the set of all dependency names.

        Args:
            parameter: SignatureParameter
        """
        if is_dependency_field(parameter.default):
            self.dependency_name_set.add(parameter.name)

    def set_field_default(self, parameter: SignatureParameter) -> None:
        """If `parameter` has defined default, map it to the parameter name in `self.defaults`.

        Args:
            parameter: SignatureParameter
        """
        if parameter.default not in {Signature.empty, MISSING}:
            self.defaults[parameter.name] = parameter.default

    def get_type_annotation_from_plugin(self, parameter: SignatureParameter, plugin: PluginProtocol) -> Any:
        """Use plugin declared for parameter annotation type to generate a pydantic model.

        Args:
            parameter:  SignatureParameter
            plugin: PluginProtocol

        Returns:
            A pydantic model to be used as a type
        """
        type_args = get_args(parameter.annotation)
        type_value = type_args[0] if type_args else parameter.annotation
        self.field_plugin_mappings[parameter.name] = PluginMapping(plugin=plugin, model_class=type_value)
        pydantic_model = plugin.to_pydantic_model_class(model_class=type_value, parameter_name=parameter.name)
        if type_args:
            return List[pydantic_model]  # type:ignore[valid-type]
        return pydantic_model

    @staticmethod
    def create_field_definition_from_parameter(parameter: SignatureParameter) -> Tuple[Any, Any]:
        """Construct an `(<annotation>, <default>)` tuple, appropriate for `pydantic.create_model()`.

        Args:
            parameter: SignatureParameter

        Returns:
            tuple[Any, Any]
        """
        if parameter.default not in {Signature.empty, MISSING}:
            return parameter.annotation, parameter.default
        if not parameter.optional:
            return parameter.annotation
        return parameter.annotation, None

    @property
    def signature_parameters(self) -> Generator[SignatureParameter, None, None]:
        """Create a generator of `SignatureParameters` to be included in the `SignatureModel` by iterating over the
        parameters of the function signature.

        Returns:
            Generator[SignatureParameter, None, None]
        """
        for name, parameter in filter(lambda x: x[0] not in SKIP_NAMES, self.signature.parameters.items()):
            yield SignatureParameter(self.fn_name, name, parameter)

    def __call__(self) -> Type[SignatureModel]:
        """Construct a `SignatureModel` type that represents the signature of `self.fn`

        Returns:
            type[SignatureModel]
        """
        try:
            for parameter in self.signature_parameters:
                self.check_for_unprovided_dependency(parameter)
                self.collect_dependency_names(parameter)
                self.set_field_default(parameter)

                if should_skip_dependency_validation(parameter):
                    if is_dependency_field(parameter.default):
                        self.field_definitions[parameter.name] = (Any, parameter.default.default)
                    else:
                        self.field_definitions[parameter.name] = Any
                    continue

                if ModelFactory.is_constrained_field(parameter.default):
                    self.field_definitions[parameter.name] = parameter.default
                    continue

                plugin = get_plugin_for_value(value=parameter.annotation, plugins=self.plugins)
                if plugin:
                    parameter.annotation = self.get_type_annotation_from_plugin(parameter, plugin)

                self.field_definitions[parameter.name] = self.create_field_definition_from_parameter(parameter)

            model = make_dataclass(
                cls_name=self.fn_name + "_signature_model",
                fields=self.field_definitions,
                bases=(SignatureModel,),
            )

            model.__slots__ = (*SignatureModel.__slots__, *set(self.field_definitions))
            model.dataclass_fields = get_dataclass_fields(model)
            model.return_annotation = self.signature.return_annotation
            model.field_plugin_mappings = self.field_plugin_mappings
            model.dependency_name_set = self.dependency_name_set
            return cast("Type[SignatureModel]", model)
        except TypeError as e:
            raise ImproperlyConfiguredException(f"Error creating signature model for '{self.fn_name}': '{e}'") from e


def get_signature_model(value: Any) -> Type[SignatureModel]:
    """Retrieve and validate the signature model from a provider or handler."""
    try:
        return cast("Type[SignatureModel]", value.signature_model)
    except AttributeError as e:  # pragma: no cover
        raise ImproperlyConfiguredException(f"The 'signature_model' attribute for {value} is not set") from e
