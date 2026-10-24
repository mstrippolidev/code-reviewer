import textwrap

import pytest

from code_reviewer.pipeline.call_depth.depth_follower import (
    MAX_HOPS,
    CallDepth,
    CallDepthFollower,
    DepthReport,
    UnknownEntry,
    WalkEnd,
)
from code_reviewer.pipeline.call_depth.project_files import FileLoader, ProjectFiles
from code_reviewer.pipeline.call_depth.thin_body import ThinBodyClassifier
from tests.helpers import load_fixture


class FakeLoader:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files
        self.requested: list[str] = []

    def load(self, path: str) -> str:
        self.requested.append(path)
        if path not in self._files:
            raise FileNotFoundError(path)
        return textwrap.dedent(self._files[path])


class ForbiddenLoader:
    def load(self, path: str) -> str:
        raise AssertionError(f"the loader must not be asked for {path}")


def build_follower(sources: dict[str, str], loader: FileLoader | None = None) -> CallDepthFollower:
    dedented = {path: textwrap.dedent(source) for path, source in sources.items()}
    return CallDepthFollower(ProjectFiles(dedented, loader), ThinBodyClassifier())


def report_for(sources: dict[str, str], path: str, function: str) -> DepthReport:
    return build_follower(sources).report_for(path, function)


def fixture_report(fixture: str, function: str) -> DepthReport:
    return report_for({"module.py": load_fixture(fixture)}, "module.py", function)


def hops_by_callee(report: DepthReport) -> dict[str, int]:
    return {call.callee: call.hops for call in report.calls}


def call_to(report: DepthReport, callee: str) -> CallDepth:
    return next(call for call in report.calls if call.callee == callee)


CROSS_FILE = {
    "app/service.py": """
        from app.pricing import PricingManager

        class Checkout:
            def __init__(self, manager: PricingManager) -> None:
                self._manager = manager

            def total(self, price):
                validate(price)
                return self._manager.price_for(price)

            def label(self):
                return "checkout"

        def validate(price):
            if price < 0:
                raise ValueError(price)
    """,
    "app/pricing.py": """
        from app.rules import apply_rule

        class PricingManager:
            def price_for(self, price):
                return apply_rule(price)
    """,
    "app/rules.py": """
        def apply_rule(price):
            if price > 100:
                return price * 0.9
            return price
    """,
}


def test_six_same_file_hops_reach_real_logic() -> None:
    report = fixture_report("complexity/hops_priority_medium.py", "checkout_total")

    call = report.calls[0]
    assert (call.hops_in_file, call.hops_in_other_files) == (6, 0)
    assert call.ended_at is WalkEnd.REAL_LOGIC


def test_five_same_file_hops_reach_real_logic() -> None:
    report = fixture_report("complexity/false_positive_same_file_helpers_within_limit.py", "checkout_total")

    assert report.calls[0].hops_in_file == 5


def test_eight_same_file_hops_reach_real_logic() -> None:
    report = fixture_report("complexity/hops_pass_through_chain.py", "checkout_total")

    call = report.calls[0]
    assert call.hops_in_file == 8
    assert call.ended_at is WalkEnd.REAL_LOGIC


def test_walk_stops_at_the_hop_limit_when_the_chain_keeps_forwarding() -> None:
    names = [f"step_{index}" for index in range(MAX_HOPS + 3)]
    forwarders = "\n".join(f"def {a}(x):\n    return {b}(x)\n" for a, b in zip(names, names[1:]))
    source = f"{forwarders}\ndef {names[-1]}(x):\n    if x:\n        return 1\n    return 0\n"

    call = report_for({"module.py": source}, "module.py", "step_0").calls[0]

    assert call.hops == MAX_HOPS
    assert call.ended_at is WalkEnd.HOP_LIMIT


def test_each_call_in_a_function_has_its_own_depth() -> None:
    report = fixture_report("complexity/uneven_call_depth.py", "price_for")

    assert hops_by_callee(report) == {"validate_price": 1, "record_price_check": 1, "discount_entry": 4}


def test_calls_that_all_reach_real_logic_at_once_have_equal_depth() -> None:
    report = fixture_report("complexity/false_positive_even_call_depth.py", "price_for")

    assert set(hops_by_callee(report).values()) == {1}


def test_calls_are_reported_in_source_order() -> None:
    source = "def f(x):\n    first(x)\n    second(x)\n    third(x)\n\ndef first(x):\n    if x:\n        return 1\n\ndef second(x):\n    if x:\n        return 1\n\ndef third(x):\n    if x:\n        return 1\n"

    report = report_for({"module.py": source}, "module.py", "f")

    assert [call.callee for call in report.calls] == ["first", "second", "third"]
    assert [call.line for call in report.calls] == [2, 3, 4]


def test_call_through_a_typed_attribute_crosses_files() -> None:
    report = report_for(CROSS_FILE, "app/service.py", "Checkout.total")

    call = next(call for call in report.calls if call.callee == "self._manager.price_for")
    assert (call.hops_in_file, call.hops_in_other_files) == (0, 2)
    assert call.other_files == ["app/pricing.py", "app/rules.py"]
    assert call.ended_at is WalkEnd.REAL_LOGIC


def test_call_inside_the_same_file_does_not_count_as_another_file() -> None:
    report = report_for(CROSS_FILE, "app/service.py", "Checkout.total")

    call = next(call for call in report.calls if call.callee == "validate")
    assert (call.hops_in_file, call.hops_in_other_files, call.other_files) == (1, 0, [])


def test_files_opened_counts_each_other_file_once() -> None:
    report = report_for(CROSS_FILE, "app/service.py", "Checkout.total")

    assert report.other_files_opened == 2


def test_method_call_on_self_stays_in_the_class() -> None:
    source = """
        class Order:
            def run(self, quantity):
                return self.price(quantity)

            def price(self, quantity):
                if quantity > 10:
                    return quantity * 0.9
                return quantity
    """

    call = report_for({"module.py": source}, "module.py", "Order.run").calls[0]

    assert (call.callee, call.hops_in_file, call.ended_at) == ("self.price", 1, WalkEnd.REAL_LOGIC)


def test_file_that_cannot_be_read_is_reported_unresolved_not_as_zero_hops() -> None:
    sources = {"app/service.py": CROSS_FILE["app/service.py"]}

    report = report_for(sources, "app/service.py", "Checkout.total")

    call = next(call for call in report.calls if call.callee == "self._manager.price_for")
    assert call.hops == 0
    assert call.ended_at is WalkEnd.UNRESOLVED
    assert "app.pricing" in call.unresolved_reason


def test_imported_name_missing_from_its_module_is_unresolved() -> None:
    sources = {
        "app/service.py": "from app.rules import missing_rule\n\ndef total(price):\n    return missing_rule(price)\n",
        "app/rules.py": "def apply_rule(price):\n    return price\n",
    }

    call = report_for(sources, "app/service.py", "total").calls[0]

    assert call.ended_at is WalkEnd.UNRESOLVED
    assert "not found in app/rules.py" in call.unresolved_reason


def test_unresolved_hop_after_a_thin_one_keeps_the_hops_already_counted() -> None:
    sources = {
        "app/service.py": "from app.rules import apply_rule\n\ndef total(price):\n    return middle(price)\n\ndef middle(price):\n    return apply_rule(price)\n",
        "app/rules.py": "def other(price):\n    return price\n",
    }

    call = report_for(sources, "app/service.py", "total").calls[0]

    assert call.hops_in_file == 1
    assert call.ended_at is WalkEnd.UNRESOLVED


def test_library_and_builtin_calls_are_left_out() -> None:
    source = """
        import json
        from fastapi import HTTPException

        def f(items):
            items.append(len(items))
            json.dumps(items)
            raise HTTPException(status_code=404)
    """

    assert report_for({"module.py": source}, "module.py", "f").calls == []


def test_class_construction_is_left_out_in_the_same_file_and_across_files() -> None:
    sources = {
        "app/service.py": "from app.models import Order\n\nclass Local:\n    pass\n\ndef make(order_id):\n    Local()\n    return Order(order_id)\n",
        "app/models.py": "class Order:\n    def __init__(self, order_id):\n        self.order_id = order_id\n",
    }

    assert report_for(sources, "app/service.py", "make").calls == []


def test_inherited_method_that_is_not_defined_in_the_file_is_left_out() -> None:
    source = "class Child(Base):\n    def run(self, x):\n        return self.inherited(x)\n"

    assert report_for({"module.py": source}, "module.py", "Child.run").calls == []


ROUTER_SOURCES = {
    "app/router.py": """
        from app.repository import Repository

        def get_repository() -> Repository:
            return Repository()

        def list_repos(repository: Repository = Depends(get_repository)):
            return repository.list_all()
    """,
    "app/repository.py": """
        class Repository:
            def list_all(self):
                if self is None:
                    return []
                return [1, 2]
    """,
}


def test_call_on_a_typed_parameter_is_followed_into_the_class_in_another_file() -> None:
    report = report_for(ROUTER_SOURCES, "app/router.py", "list_repos")

    call = call_to(report, "repository.list_all")
    assert (call.callee, call.hops_in_other_files, call.other_files) == (
        "repository.list_all",
        1,
        ["app/repository.py"],
    )
    assert call.ended_at is WalkEnd.REAL_LOGIC


def test_depends_provider_in_a_parameter_default_is_reported_before_the_body_calls() -> None:
    report = report_for(ROUTER_SOURCES, "app/router.py", "list_repos")

    assert [call.callee for call in report.calls] == ["get_repository", "repository.list_all"]


SESSION_SOURCE = """
    def get_session():
        return open_session()

    def open_session():
        if cached_session:
            return cached_session
        return make_session()

    def {signature}:
        return session
"""


def test_depends_provider_is_followed_through_the_functions_that_only_forward() -> None:
    source = SESSION_SOURCE.format(signature="route(session=Depends(get_session))")

    call = call_to(report_for({"app/router.py": source}, "app/router.py", "route"), "get_session")

    assert (call.hops_in_file, call.ended_at) == (2, WalkEnd.REAL_LOGIC)


def test_keyword_only_depends_provider_is_followed() -> None:
    source = SESSION_SOURCE.format(signature="route(*, session=Depends(get_session))")

    report = report_for({"app/router.py": source}, "app/router.py", "route")

    assert hops_by_callee(report) == {"get_session": 2}


def test_default_that_is_not_depends_is_not_reported_as_a_call() -> None:
    source = SESSION_SOURCE.format(signature="route(limit=10, name=open_session())")

    report = report_for({"app/router.py": source}, "app/router.py", "route")

    assert report.calls == []


def test_depends_without_a_provider_is_left_out() -> None:
    source = SESSION_SOURCE.format(signature="route(session=Depends())")

    report = report_for({"app/router.py": source}, "app/router.py", "route")

    assert report.calls == []


def test_depends_on_a_library_provider_is_left_out() -> None:
    source = """
        from somelibrary.auth import current_user

        def route(user=Depends(current_user)):
            return user
    """

    report = report_for({"app/router.py": source}, "app/router.py", "route")

    assert report.calls == []


def test_call_on_a_typed_parameter_of_a_class_in_the_same_file() -> None:
    source = """
        class Store:
            def find(self, key):
                if key:
                    return key
                return None

        def read(store: Store, key):
            return store.find(key)
    """

    call = report_for({"module.py": source}, "module.py", "read").calls[0]

    assert (call.hops_in_file, call.ended_at) == (1, WalkEnd.REAL_LOGIC)


def test_typed_parameter_works_inside_a_method_alongside_self() -> None:
    source = """
        class Store:
            def find(self, key):
                if key:
                    return key
                return None

        class Service:
            def run(self, store: Store, key):
                return store.find(key)
    """

    call = report_for({"module.py": source}, "module.py", "Service.run").calls[0]

    assert call.callee == "store.find"
    assert call.hops_in_file == 1


def test_typed_parameters_of_a_followed_function_are_used_for_the_next_hop() -> None:
    source = """
        class Store:
            def find(self, key):
                if key:
                    return key
                return None

        def handler(store: Store, key):
            return fetch(store, key)

        def fetch(store: Store, key):
            return store.find(key)
    """

    call = report_for({"module.py": source}, "module.py", "handler").calls[0]

    assert call.hops == 2
    assert call.ended_at is WalkEnd.REAL_LOGIC


def test_call_on_an_untyped_parameter_is_left_out() -> None:
    source = "def read(store, key):\n    return store.find(key)\n"

    assert report_for({"module.py": source}, "module.py", "read").calls == []


def test_call_on_a_parameter_typed_with_a_builtin_or_library_class_is_left_out() -> None:
    source = (
        "from sqlalchemy.orm import Session\n\n"
        "def read(items: list, session: Session, name: str):\n"
        "    items.append(name.upper())\n"
        "    return session.get(name)\n"
    )

    assert report_for({"module.py": source}, "module.py", "read").calls == []


def test_functions_that_forward_to_each_other_end_in_a_cycle() -> None:
    source = "def a(x):\n    return b(x)\n\ndef b(x):\n    return a(x)\n"

    call = report_for({"module.py": source}, "module.py", "a").calls[0]

    assert call.hops == 2
    assert call.ended_at is WalkEnd.CYCLE


def test_forwarding_to_a_library_ends_the_walk_outside_the_project() -> None:
    source = "from requests import get\n\ndef entry(x):\n    return forward(x)\n\ndef forward(x):\n    return get(x)\n"

    call = report_for({"module.py": source}, "module.py", "entry").calls[0]

    assert call.hops == 1
    assert call.ended_at is WalkEnd.FORWARDS_OUTSIDE


def test_files_missing_from_the_pr_are_read_through_the_loader() -> None:
    loader = FakeLoader({"app/pricing.py": CROSS_FILE["app/pricing.py"], "app/rules.py": CROSS_FILE["app/rules.py"]})
    follower = build_follower({"app/service.py": CROSS_FILE["app/service.py"]}, loader)

    report = follower.report_for("app/service.py", "Checkout.total")

    call = next(call for call in report.calls if call.callee == "self._manager.price_for")
    assert (call.hops_in_other_files, call.ended_at) == (2, WalkEnd.REAL_LOGIC)
    assert loader.requested == ["app/pricing.py", "app/rules.py"]


def test_pr_files_are_used_before_the_loader_is_asked() -> None:
    follower = build_follower(CROSS_FILE, ForbiddenLoader())

    report = follower.report_for("app/service.py", "Checkout.total")

    assert report.other_files_opened == 2


def test_unknown_file_raises() -> None:
    with pytest.raises(UnknownEntry, match="app/other.py"):
        build_follower(CROSS_FILE).report_for("app/other.py", "total")


def test_unknown_function_raises() -> None:
    with pytest.raises(UnknownEntry, match="nope"):
        build_follower(CROSS_FILE).report_for("app/service.py", "Checkout.nope")


def test_reports_cover_every_function_that_calls_project_code_and_skip_the_rest() -> None:
    reports = build_follower(CROSS_FILE).reports_for("app/service.py")

    assert [report.function for report in reports] == ["Checkout.total"]


def test_reports_for_an_unknown_file_raises() -> None:
    with pytest.raises(UnknownEntry):
        build_follower(CROSS_FILE).reports_for("app/other.py")


def test_hops_is_the_sum_of_hops_in_the_file_and_in_other_files() -> None:
    call = CallDepth(
        callee="f", line=1, hops_in_file=2, hops_in_other_files=3, other_files=["a.py"], ended_at=WalkEnd.REAL_LOGIC
    )

    assert call.hops == 5


def test_call_text_names_the_line_the_callee_and_both_counts() -> None:
    call = CallDepth(
        callee="validate", line=9, hops_in_file=1, hops_in_other_files=0, other_files=[], ended_at=WalkEnd.REAL_LOGIC
    )

    assert call.to_prompt_text() == (
        "line 9 validate: hops in this file=1, hops in other files=0; ends at code that decides something"
    )


def test_call_text_lists_the_other_files_it_opened() -> None:
    call = CallDepth(
        callee="self._manager.price_for",
        line=10,
        hops_in_file=0,
        hops_in_other_files=2,
        other_files=["app/pricing.py", "app/rules.py"],
        ended_at=WalkEnd.REAL_LOGIC,
    )

    assert "hops in other files=2 (app/pricing.py, app/rules.py);" in call.to_prompt_text()


def test_call_text_gives_the_reason_a_call_was_not_followed() -> None:
    call = CallDepth(
        callee="compute",
        line=4,
        hops_in_file=0,
        hops_in_other_files=0,
        other_files=[],
        ended_at=WalkEnd.UNRESOLVED,
        unresolved_reason="the file for module 'app.pricing' was not provided",
    )

    assert call.to_prompt_text().endswith("could not be followed: the file for module 'app.pricing' was not provided")


@pytest.mark.parametrize("ended_at", list(WalkEnd))
def test_every_way_a_walk_can_end_has_text(ended_at: WalkEnd) -> None:
    call = CallDepth(callee="f", line=1, hops_in_file=1, hops_in_other_files=0, other_files=[], ended_at=ended_at)

    assert "; " in call.to_prompt_text()


def test_report_text_has_a_header_and_one_indented_line_per_call() -> None:
    report = report_for(CROSS_FILE, "app/service.py", "Checkout.total")

    lines = report.to_prompt_text().splitlines()

    assert lines[0] == "Checkout.total: other files opened=2"
    assert [line.startswith("  line ") for line in lines[1:]] == [True, True]
