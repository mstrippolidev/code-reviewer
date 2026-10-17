"""
    Measures how deep each call inside one function goes before it reaches code
    that makes a decision.

    For every call in the function it works out what is being called
    (_callee_of), where that lives (_target_for: this file first, then the
    files it imports from), and asks ThinBodyClassifier whether it only
    forwards. It keeps following while it does, and stops at the first callee
    that decides something, at a cycle, at a call it cannot resolve, or at
    MAX_HOPS.

    Example: price_for calls three functions
        execute_function(price)         -> 1 hop, real logic
        another_function(price)         -> 1 hop, real logic
        self._facade.discount(price)    -> 4 hops (3 thin, then real logic)
    so its calls have depths 1, 1 and 4: uneven.

    A call into project code whose file cannot be read is reported as
    unresolved, never as zero hops.
"""
import ast
from enum import Enum

from pydantic import BaseModel

from code_reviewer.pipeline.call_depth.project_files import ExternalCall, ProjectFiles, UnresolvedCall
from code_reviewer.pipeline.call_depth.symbol_index import ModuleIndex
from code_reviewer.pipeline.call_depth.thin_body import FunctionNode, ThinBodyClassifier

MAX_HOPS = 8


class WalkEnd(str, Enum):
    REAL_LOGIC = "real_logic"
    FORWARDS_OUTSIDE = "forwards_outside_project"
    UNRESOLVED = "unresolved"
    CYCLE = "cycle"
    HOP_LIMIT = "hop_limit"


class CallDepth(BaseModel):
    callee: str
    line: int
    hops_in_file: int
    hops_in_other_files: int
    other_files: list[str]
    ended_at: WalkEnd
    unresolved_reason: str = ""

    @property
    def hops(self) -> int:
        return self.hops_in_file + self.hops_in_other_files


class DepthReport(BaseModel):
    function: str
    path: str
    calls: list[CallDepth]

    @property
    def other_files_opened(self) -> int:
        return len({file for call in self.calls for file in call.other_files})


class UnknownEntry(Exception):
    """Raised when the requested file or function is not in the provided files."""


class _Callee(BaseModel):
    owner: str | None
    name: str


class _Target(BaseModel):
    path: str
    owner: str | None
    name: str


class CallDepthFollower:
    def __init__(self, files: ProjectFiles, classifier: ThinBodyClassifier) -> None:
        self._files = files
        self._classifier = classifier

    def report_for(self, path: str, function_name: str) -> DepthReport:
        if not self._files.has(path):
            raise UnknownEntry(f"file {path!r} was not provided")
        owner = function_name.rpartition(".")[0] or None
        entry = _Target(path=path, owner=owner, name=function_name.rpartition(".")[2])
        try:
            function = self._function_in(entry)
        except KeyError as error:
            raise UnknownEntry(f"{function_name!r} is not defined in {path!r}") from error
        calls = []
        for call in self._calls_in(function):
            try:
                calls.append(self._walk(call, self._files.at(path), owner))
            except ExternalCall:
                continue
        return DepthReport(function=function_name, path=path, calls=calls)

    def _calls_in(self, function: FunctionNode) -> list[ast.Call]:
        calls = [node for statement in function.body for node in ast.walk(statement) if isinstance(node, ast.Call)]
        return sorted(calls, key=lambda call: (call.lineno, call.col_offset))

    def _walk(self, call: ast.Call, module: ModuleIndex, owner: str | None) -> CallDepth:
        callee, line, entry_path = ast.unparse(call.func), call.lineno, module.path
        visited: list[_Target] = []
        ended_at, reason = WalkEnd.HOP_LIMIT, ""
        for _ in range(MAX_HOPS):
            try:
                target = self._target_for(self._callee_of(call, module, owner), module)
            except ExternalCall:
                if not visited:
                    raise
                ended_at = WalkEnd.FORWARDS_OUTSIDE
                break
            except UnresolvedCall as error:
                ended_at, reason = WalkEnd.UNRESOLVED, str(error)
                break
            if target in visited:
                ended_at = WalkEnd.CYCLE
                break
            visited.append(target)
            function = self._function_in(target)
            if not self._classifier.is_thin(function):
                ended_at = WalkEnd.REAL_LOGIC
                break
            call = self._classifier.forwarded_call(function)
            module, owner = self._files.at(target.path), target.owner
        other_files = [target.path for target in visited if target.path != entry_path]
        return CallDepth(
            callee=callee,
            line=line,
            hops_in_file=len(visited) - len(other_files),
            hops_in_other_files=len(other_files),
            other_files=sorted(set(other_files)),
            ended_at=ended_at,
            unresolved_reason=reason,
        )

    def _function_in(self, target: _Target) -> FunctionNode:
        return self._files.at(target.path).definitions[(target.owner, target.name)]

    def _callee_of(self, call: ast.Call, module: ModuleIndex, owner: str | None) -> _Callee:
        func = call.func
        if isinstance(func, ast.Name):
            return _Callee(owner=None, name=func.id)
        if isinstance(func, ast.Attribute) and owner:
            receiver = func.value
            if isinstance(receiver, ast.Name) and receiver.id == "self":
                return _Callee(owner=owner, name=func.attr)
            if isinstance(receiver, ast.Attribute) and self._is_self(receiver.value):
                attribute_class = module.attribute_types.get((owner, receiver.attr))
                if attribute_class:
                    return _Callee(owner=attribute_class, name=func.attr)
        raise ExternalCall(ast.unparse(func))

    def _is_self(self, node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == "self"

    def _target_for(self, callee: _Callee, module: ModuleIndex) -> _Target:
        key = (callee.owner, callee.name)
        if key in module.definitions:
            return _Target(path=module.path, owner=callee.owner, name=callee.name)
        imported_name = callee.owner or callee.name
        if imported_name not in module.imports:
            raise ExternalCall(callee.name)
        imported_module = self._files.module_named(module.imports[imported_name])
        if key in imported_module.definitions:
            return _Target(path=imported_module.path, owner=callee.owner, name=callee.name)
        if callee.owner is None and callee.name in imported_module.classes:
            raise ExternalCall(callee.name)
        raise UnresolvedCall(f"'{callee.name}' was not found in {imported_module.path}")
