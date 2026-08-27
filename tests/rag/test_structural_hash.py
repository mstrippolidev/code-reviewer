"""
    Tests for compute_structural_hash: equivalence under renaming, and
    sensitivity to genuine structural differences.
"""
import pytest

from code_reviewer.rag.errors import StructuralHashError
from code_reviewer.rag.structural_hash import compute_structural_hash


def test_identical_code_produces_the_same_hash() -> None:
    """Verify hashing is deterministic for unchanged input."""
    code = "def add(a, b):\n    return a + b\n"

    assert compute_structural_hash(code) == compute_structural_hash(code)


def test_renamed_parameters_and_variables_produce_the_same_hash() -> None:
    """Verify a Type-2 clone (renamed identifiers, same logic) hashes equal."""
    original = "def add(a, b):\n    return a + b\n"
    renamed = "def add(first_value, second_value):\n    return first_value + second_value\n"

    assert compute_structural_hash(original) == compute_structural_hash(renamed)


def test_renamed_function_name_produces_the_same_hash() -> None:
    """Verify the function's own name is normalized, not just its body."""
    original = "def add(a, b):\n    return a + b\n"
    renamed = "def sum_values(a, b):\n    return a + b\n"

    assert compute_structural_hash(original) == compute_structural_hash(renamed)


def test_renamed_class_name_produces_the_same_hash() -> None:
    """Verify class names are normalized the same way function names are."""
    original = "class OrderTotal:\n    def get(self, items):\n        return sum(items)\n"
    renamed = "class CartTotal:\n    def get(self, items):\n        return sum(items)\n"

    assert compute_structural_hash(original) == compute_structural_hash(renamed)


def test_different_literal_values_produce_the_same_hash() -> None:
    """Verify a Type-2 clone with changed constants hashes equal."""
    original = "def get_limit():\n    return 100\n"
    changed_literal = "def get_limit():\n    return 250\n"

    assert compute_structural_hash(original) == compute_structural_hash(changed_literal)


def test_different_docstring_produces_the_same_hash() -> None:
    """Verify a Type-1 clone with a different docstring hashes equal, since
    docstrings are string literals normalized like any other constant."""
    original = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n'
    redocumented = 'def add(a, b):\n    """Sum a pair of values."""\n    return a + b\n'

    assert compute_structural_hash(original) == compute_structural_hash(redocumented)


def test_different_operator_produces_a_different_hash() -> None:
    """Verify genuinely different logic is not collapsed to the same hash."""
    addition = "def combine(a, b):\n    return a + b\n"
    subtraction = "def combine(a, b):\n    return a - b\n"

    assert compute_structural_hash(addition) != compute_structural_hash(subtraction)


def test_different_control_flow_produces_a_different_hash() -> None:
    """Verify an added branch changes the hash even with the same identifiers."""
    unconditional = "def pick(a, b):\n    return a + b\n"
    conditional = "def pick(a, b):\n    if a > 0:\n        return a\n    return b\n"

    assert compute_structural_hash(unconditional) != compute_structural_hash(conditional)


def test_invalid_python_syntax_raises_structural_hash_error() -> None:
    """Verify unparseable input surfaces as StructuralHashError, not a raw SyntaxError."""
    with pytest.raises(StructuralHashError):
        compute_structural_hash("def broken(:\n    pass\n")
