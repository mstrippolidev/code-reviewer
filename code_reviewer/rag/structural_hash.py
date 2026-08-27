"""
    Deterministic structural fingerprinting for Type-1/Type-2/Type-3 code
    clone detection.
"""
import ast
import hashlib

from code_reviewer.rag.errors import StructuralHashError


def compute_structural_hash(code: str) -> str:
    """Fingerprint one code chunk's structure, blind to identifier names
    and literal values — a renamed or re-valued copy hashes identical.

    Raises:
        StructuralHashError: If code is not valid Python syntax.
    """
    tree = _parse(code)
    normalized_tree = _StructuralNormalizer().normalize(tree)
    return hashlib.sha256(ast.dump(normalized_tree).encode("utf-8")).hexdigest()


def _parse(code: str) -> ast.AST:
    try:
        return ast.parse(code)
    except (SyntaxError, ValueError) as error:
        raise StructuralHashError("Failed to parse chunk as valid Python syntax.") from error


class _StructuralNormalizer(ast.NodeTransformer):
    """Rewrites every identifier and literal in an AST into a positional
    placeholder, so two structurally identical chunks normalize to the
    same tree regardless of naming or literal values.
    """

    def __init__(self) -> None:
        self._placeholder_by_name: dict[str, str] = {}

    def normalize(self, tree: ast.AST) -> ast.AST:
        normalized_tree = self.visit(tree)
        ast.fix_missing_locations(normalized_tree)
        return normalized_tree

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self._placeholder_for(node.id)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = self._placeholder_for(node.arg)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = self._placeholder_for(node.name)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = self._placeholder_for(node.name)
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.name = self._placeholder_for(node.name)
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        node.value = "_LITERAL_"
        return node

    def _placeholder_for(self, original_name: str) -> str:
        if original_name not in self._placeholder_by_name:
            self._placeholder_by_name[original_name] = f"_ID_{len(self._placeholder_by_name)}"
        return self._placeholder_by_name[original_name]
