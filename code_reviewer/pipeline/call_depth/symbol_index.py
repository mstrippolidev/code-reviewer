"""
    Reads one Python file and records what a call-depth walk needs to know about it:
    which functions and methods it defines, which names it imports from other
    modules, and the class behind each `self.<attribute>` set in `__init__`.

    Used to know if a function call live inside the same file or not.

    Example: for
        from app.pricing import PricingManager

        class Checkout:
            def __init__(self, manager: PricingManager) -> None:
                self._manager = manager

            def total(self, price):
                return self._manager.price_for(price)

    definitions      -> {("Checkout", "__init__"): ..., ("Checkout", "total"): ...}
    classes          -> {"Checkout"}
    attribute_types  -> {("Checkout", "_manager"): "PricingManager"}
    imports          -> {"PricingManager": "app.pricing"}

    definitions is keyed by (class name, function name); a plain function has
    None as its class name, e.g. (None, "validate").
"""
import ast

from code_reviewer.pipeline.call_depth.thin_body import FunctionNode


class ModuleIndex:
    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        self.definitions: dict[tuple[str | None, str], FunctionNode] = {}
        self.classes: set[str] = set()
        self.attribute_types: dict[tuple[str, str], str] = {}
        self.imports: dict[str, str] = {}
        for node in tree.body:
            self._index(node)

    def _index(self, node: ast.stmt) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.definitions[(None, node.name)] = node
        elif isinstance(node, ast.ClassDef):
            self._index_class(node)
        elif isinstance(node, ast.ImportFrom):
            self._index_import(node)

    def _index_class(self, class_node: ast.ClassDef) -> None:
        self.classes.add(class_node.name)
        for member in class_node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            self.definitions[(class_node.name, member.name)] = member
            if member.name == "__init__":
                self._index_attribute_types(class_node.name, member)

    def _index_attribute_types(self, class_name: str, init: FunctionNode) -> None:
        parameter_types = {
            parameter.arg: parameter.annotation.id
            for parameter in init.args.args
            if isinstance(parameter.annotation, ast.Name)
        }
        for statement in init.body:
            self._index_assignment(class_name, statement, parameter_types)

    def _index_assignment(self, class_name: str, statement: ast.stmt, parameter_types: dict[str, str]) -> None:
        if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Name):
            return
        target = statement.targets[0]
        if isinstance(target, ast.Attribute) and statement.value.id in parameter_types:
            self.attribute_types[(class_name, target.attr)] = parameter_types[statement.value.id]

    def _index_import(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.imports[alias.name] = node.module or ""
