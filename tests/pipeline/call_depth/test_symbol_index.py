import ast
import textwrap

from code_reviewer.pipeline.call_depth.symbol_index import ModuleIndex, annotated_parameters


def build_index(source: str, path: str = "app/service.py") -> ModuleIndex:
    return ModuleIndex(path, ast.parse(textwrap.dedent(source)))


SERVICE = """
    from app.pricing import PricingManager, Discount

    class Checkout:
        def __init__(self, manager: PricingManager, discount: Discount) -> None:
            self._manager = manager
            self._discount = discount

        def total(self, price):
            return self._manager.price_for(price)

    def validate(price):
        if price < 0:
            raise ValueError(price)

    async def fetch(price):
        return price
"""


def test_functions_and_methods_share_one_table_keyed_by_class_and_name() -> None:
    index = build_index(SERVICE)

    assert set(index.definitions) == {
        ("Checkout", "__init__"),
        ("Checkout", "total"),
        (None, "validate"),
        (None, "fetch"),
    }


def test_definitions_hold_the_function_nodes() -> None:
    index = build_index(SERVICE)

    assert index.definitions[(None, "validate")].name == "validate"
    assert isinstance(index.definitions[(None, "fetch")], ast.AsyncFunctionDef)


def test_classes_are_recorded_by_name() -> None:
    assert build_index(SERVICE).classes == {"Checkout"}


def test_attribute_types_come_from_init_annotations() -> None:
    index = build_index(SERVICE)

    assert index.attribute_types == {
        ("Checkout", "_manager"): "PricingManager",
        ("Checkout", "_discount"): "Discount",
    }


def test_attribute_without_an_annotated_parameter_has_no_type() -> None:
    source = """
        class Checkout:
            def __init__(self, manager, rate: float = 1.0) -> None:
                self._manager = manager
                self._cache = {}
                self._rate = 2.0
    """

    assert build_index(source).attribute_types == {}


def test_attribute_types_are_only_read_from_init() -> None:
    source = """
        class Checkout:
            def configure(self, manager: PricingManager) -> None:
                self._manager = manager
    """

    assert build_index(source).attribute_types == {}


def test_every_name_in_a_from_import_maps_to_its_module() -> None:
    index = build_index(SERVICE)

    assert index.imports == {"PricingManager": "app.pricing", "Discount": "app.pricing"}


def test_functions_nested_in_a_function_are_not_indexed() -> None:
    source = """
        def outer():
            def inner():
                return 1
            return inner
    """

    assert set(build_index(source).definitions) == {(None, "outer")}


def test_annotated_parameters_reads_every_kind_of_parameter_with_a_simple_type() -> None:
    function = ast.parse("def f(a: A, /, b: B, *, c: C, d, e: list[int], g: H | None): ...").body[0]

    assert annotated_parameters(function) == {"a": "A", "b": "B", "c": "C"}


def test_path_is_kept() -> None:
    assert build_index("x = 1\n", path="app/rules.py").path == "app/rules.py"


def test_file_with_no_definitions_has_empty_tables() -> None:
    index = build_index("x = 1\n")

    assert index.definitions == {}
    assert index.classes == set()
    assert index.imports == {}
