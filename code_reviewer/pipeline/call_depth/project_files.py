"""
    Holds the indexed files of the project being reviewed and finds the one an
    import points to.

    An import only gives a module name, e.g. `from app.pricing import X` gives
    "app.pricing". module_named turns that into the file we were given for it
    ("app/pricing.py" or "app/pricing/__init__.py").

    The files given up front are the PR's. When a candidate file is not among
    them, an optional FileLoader is asked for it (for a registered repo, the
    indexed copy), and the result is parsed and kept so it is loaded once.

    When no file is found it decides between two cases:
        - the module belongs to this project but its file was not provided
          -> UnresolvedCall, the depth walk reports it as unresolved
        - the module belongs to a library (json, fastapi, ...)
          -> ExternalCall, the depth walk ignores it
    A module belongs to the project when its top package matches the first
    folder (or file) of any provided path: "app.missing" is project code when
    "app/service.py" was provided.
"""
import ast
from typing import Protocol

from code_reviewer.pipeline.call_depth.symbol_index import ModuleIndex


class ExternalCall(Exception):
    """Raised when a call leaves project code: a builtin, a library, or an unknown receiver."""


class UnresolvedCall(Exception):
    """Raised when a call points into project code that cannot be found."""


class FileLoader(Protocol):
    def load(self, path: str) -> str: ...


class ProjectFiles:
    def __init__(self, sources: dict[str, str], loader: FileLoader | None = None) -> None:
        self._loader = loader
        self._modules = {path: ModuleIndex(path, ast.parse(source)) for path, source in sources.items()}

    def has(self, path: str) -> bool:
        return path in self._modules

    def at(self, path: str) -> ModuleIndex:
        return self._modules[path]

    def module_named(self, module_name: str) -> ModuleIndex:
        base = module_name.replace(".", "/")
        for candidate in (f"{base}.py", f"{base}/__init__.py"):
            try:
                return self._module_at(candidate)
            except FileNotFoundError:
                continue
        if self._is_project_module(module_name):
            raise UnresolvedCall(f"the file for module '{module_name}' was not provided")
        raise ExternalCall(module_name)

    def _module_at(self, path: str) -> ModuleIndex:
        if path not in self._modules:
            self._modules[path] = self._load(path)
        return self._modules[path]

    def _load(self, path: str) -> ModuleIndex:
        if self._loader is None:
            raise FileNotFoundError(path)
        return ModuleIndex(path, ast.parse(self._loader.load(path)))

    def _is_project_module(self, module_name: str) -> bool:
        top_package = module_name.split(".")[0]
        return any(path.split("/")[0].removesuffix(".py") == top_package for path in self._modules)
