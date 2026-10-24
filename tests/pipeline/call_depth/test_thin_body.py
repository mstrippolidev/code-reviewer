import ast

import pytest

from code_reviewer.pipeline.call_depth.thin_body import FunctionNode, NotAForwarder, ThinBodyClassifier


def parse_function(source: str) -> FunctionNode:
    node = ast.parse(source).body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return node


@pytest.mark.parametrize(
    "source",
    [
        "def f(price):\n    return g(price)",
        "def f(self, price):\n    return self._rule.calculate(price)",
        "def f(price):\n    g(price)",
        "def f(price):\n    return g(price, retries=3)",
        "def f(price, *args, **kwargs):\n    return g(price, *args, **kwargs)",
        "def f(price):\n    '''Docs.'''\n    return g(price)",
        "async def f(price):\n    return await g(price)",
    ],
)
def test_function_that_only_forwards_is_thin(source: str) -> None:
    assert ThinBodyClassifier().is_thin(parse_function(source)) is True


@pytest.mark.parametrize(
    "source",
    [
        "def f(price):\n    if price:\n        return g(price)\n    return 0",
        "def f(price):\n    validate(price)\n    return g(price)",
        "def f(price):\n    return g(price * 2)",
        "def f(price):\n    return g(price) + 1",
        "def f(price):\n    return price",
        "def f(price):\n    return g(other)",
        "def f(price):\n    return g(helper(price))",
        "def f(price):\n    raise ValueError(price)",
        "def f(price):\n    pass",
    ],
)
def test_function_that_does_more_than_forward_is_not_thin(source: str) -> None:
    assert ThinBodyClassifier().is_thin(parse_function(source)) is False


def test_forwarded_call_is_the_single_call_in_the_body() -> None:
    call = ThinBodyClassifier().forwarded_call(parse_function("def f(price):\n    return g(price)"))

    assert isinstance(call.func, ast.Name)
    assert call.func.id == "g"


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("def f(price):\n    validate(price)\n    return g(price)", "body is not a single statement"),
        ("def f(price):\n    if price:\n        return g(price)", "statement is not a return or a bare call"),
        ("def f(price):\n    return price", "statement does not call anything"),
        ("def f(price):\n    return g(price * 2)", "an argument is computed, not passed through"),
    ],
)
def test_forwarded_call_raises_with_the_reason_it_is_not_a_forwarder(source: str, reason: str) -> None:
    with pytest.raises(NotAForwarder, match=reason):
        ThinBodyClassifier().forwarded_call(parse_function(source))
