"""
    Tests for PythonCodeSplit: pure AST logic, no LLM involved.
"""
import pytest

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.interface import CodeChunk
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit


@pytest.fixture
def splitter() -> PythonCodeSplit:
    return PythonCodeSplit()


def test_splits_one_function_into_one_chunk(splitter: PythonCodeSplit) -> None:
    source = "def foo():\n    return 1\n"

    chunks = splitter.split_code(source)

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "FunctionDef"
    assert chunks[0].name == "foo"
    assert chunks[0].code == "def foo():\n    return 1"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2


def test_splits_multiple_top_level_defs_in_source_order(splitter: PythonCodeSplit) -> None:
    source = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"

    chunks = splitter.split_code(source)

    assert [chunk.name for chunk in chunks] == ["foo", "bar"]
    assert chunks[0].start_line == 1
    assert chunks[1].start_line == 5


def test_class_becomes_one_chunk_including_its_methods(splitter: PythonCodeSplit) -> None:
    source = (
        "class Shape:\n"
        "    def __init__(self, side):\n"
        "        self._side = side\n"
        "\n"
        "    def area(self):\n"
        "        return self._side * self._side\n"
    )

    chunks = splitter.split_code(source)

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "ClassDef"
    assert chunks[0].name == "Shape"
    assert "__init__" in chunks[0].code
    assert "area" in chunks[0].code


def test_nested_function_stays_embedded_in_its_parent_chunk(splitter: PythonCodeSplit) -> None:
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n"
    )

    chunks = splitter.split_code(source)

    assert len(chunks) == 1
    assert chunks[0].name == "outer"
    assert "def inner" in chunks[0].code


def test_decorators_are_included_in_the_chunk(splitter: PythonCodeSplit) -> None:
    source = "class Box:\n    @property\n    def area(self):\n        return 1\n"

    chunks = splitter.split_code(source)

    assert chunks[0].start_line == 1
    assert "@property" in chunks[0].code


def test_multiple_decorators_use_the_topmost_decorator_as_start_line(splitter: PythonCodeSplit) -> None:
    source = "@first\n@second\ndef handler():\n    return 1\n"

    chunks = splitter.split_code(source)

    assert chunks[0].start_line == 1
    assert chunks[0].code.startswith("@first")


def test_async_function_is_split_correctly(splitter: PythonCodeSplit) -> None:
    source = "async def fetch():\n    return 1\n"

    chunks = splitter.split_code(source)

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "AsyncFunctionDef"
    assert chunks[0].name == "fetch"


def test_imports_and_docstring_are_excluded_but_still_count_toward_line_numbers(splitter: PythonCodeSplit) -> None:
    source = (
        '"""Module docstring."""\n'
        "import os\n"
        "\n"
        "\n"
        "def foo():\n"
        "    return os.getcwd()\n"
    )

    chunks = splitter.split_code(source)

    assert chunks[0].start_line == 5
    assert "import os" not in chunks[0].code


def test_module_with_no_functions_or_classes_returns_no_chunks(splitter: PythonCodeSplit) -> None:
    source = "x = 1\ny = 2\n"

    chunks = splitter.split_code(source)

    assert chunks == []


def test_invalid_syntax_raises_code_chunking_error(splitter: PythonCodeSplit) -> None:
    with pytest.raises(CodeChunkingError):
        splitter.split_code("def broken(:\n    pass")


def test_code_chunk_is_immutable(splitter: PythonCodeSplit) -> None:
    chunks = splitter.split_code("def foo():\n    return 1\n")

    with pytest.raises(Exception):
        chunks[0].name = "renamed"


def test_code_chunk_can_be_constructed_directly() -> None:
    chunk = CodeChunk(chunk_type="FunctionDef", name="foo", code="def foo(): ...", start_line=1, end_line=1)

    assert chunk.name == "foo"
