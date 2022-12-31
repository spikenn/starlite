from typing import Protocol, Union, List
from pydantic import DirectoryPath

# the template class of the respective library
from some_lib import SomeTemplate

from starlite.template import TemplateEngineProtocol


class StdlibTemplateEngineProtocol(TemplateEngineProtocol):
    def __init__(self, directory: Union[DirectoryPath, List[DirectoryPath]]) -> None:
        """Builds a template engine."""
        ...

    def get_template(self, template_name: str) -> SomeTemplate:
        """Loads the template with template_name and returns it."""
        ...
