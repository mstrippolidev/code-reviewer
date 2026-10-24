"""
    Pins the call-depth report each CMPLX call-depth fixture produces, so a
    failing test in tests/agents/test_complexity_call_depth.py points at the
    model or the prompt, never at a fixture that stopped meaning what it says.
"""
import pytest
from pydantic import BaseModel

from code_reviewer.pipeline.call_depth.depth_follower import CallDepth, WalkEnd
from tests.call_depth_scenario import CallDepthScenario

ORDERS_ROUTER = "app/routers/orders.py"


class ExpectedCall(BaseModel):
    fixture: str
    path: str
    function: str
    callee: str
    hops_in_file: int
    hops_in_other_files: int
    ended_at: WalkEnd


class ExpectedFiles(BaseModel):
    fixture: str
    path: str
    function: str
    other_files_opened: int


def call_in(expected: ExpectedCall) -> CallDepth:
    report = CallDepthScenario(expected.fixture).report_for(expected.path, expected.function)
    return next(call for call in report.calls if call.callee == expected.callee)


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/cross_file_chain",
                path=ORDERS_ROUTER,
                function="create_order",
                callee="place_order",
                hops_in_file=0,
                hops_in_other_files=4,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="cross-file-chain-four-files",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/three_other_files",
                path=ORDERS_ROUTER,
                function="create_order",
                callee="place_order",
                hops_in_file=0,
                hops_in_other_files=3,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="three-other-files",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/mixed_chain",
                path=ORDERS_ROUTER,
                function="create_order",
                callee="_submit",
                hops_in_file=2,
                hops_in_other_files=4,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="mixed-chain",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/hop_limit_chain.py",
                path="hop_limit_chain.py",
                function="checkout_total",
                callee="_stage_1",
                hops_in_file=8,
                hops_in_other_files=0,
                ended_at=WalkEnd.HOP_LIMIT,
            ),
            id="hop-limit",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/hops_priority_medium.py",
                path="hops_priority_medium.py",
                function="checkout_total",
                callee="price_with_rules",
                hops_in_file=6,
                hops_in_other_files=0,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="six-same-file-hops",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/hops_pass_through_chain.py",
                path="hops_pass_through_chain.py",
                function="checkout_total",
                callee="price_with_rules",
                hops_in_file=8,
                hops_in_other_files=0,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="eight-same-file-hops",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/false_positive_same_file_helpers_within_limit.py",
                path="false_positive_same_file_helpers_within_limit.py",
                function="checkout_total",
                callee="price_with_rules",
                hops_in_file=5,
                hops_in_other_files=0,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="five-same-file-hops",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/uneven_call_depth.py",
                path="uneven_call_depth.py",
                function="price_for",
                callee="discount_entry",
                hops_in_file=4,
                hops_in_other_files=0,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="uneven-same-file-deep-call",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/uneven_call_depth.py",
                path="uneven_call_depth.py",
                function="price_for",
                callee="validate_price",
                hops_in_file=1,
                hops_in_other_files=0,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="uneven-same-file-shallow-sibling",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/uneven_cross_file",
                path="app/routers/checkout.py",
                function="checkout",
                callee="ship_cart",
                hops_in_file=0,
                hops_in_other_files=4,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="uneven-cross-file-deep-call",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/uneven_cross_file",
                path="app/routers/checkout.py",
                function="checkout",
                callee="price_cart",
                hops_in_file=0,
                hops_in_other_files=1,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="uneven-cross-file-shallow-sibling",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/false_positive_even_call_depth.py",
                path="false_positive_even_call_depth.py",
                function="price_for",
                callee="apply_discount",
                hops_in_file=1,
                hops_in_other_files=0,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="even-depth",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/deciding_layers",
                path=ORDERS_ROUTER,
                function="create_order",
                callee="place_order",
                hops_in_file=0,
                hops_in_other_files=1,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="deciding-layer-stops-the-walk",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/depends_route",
                path="app/routers/repos.py",
                function="list_repos",
                callee="current_user",
                hops_in_file=0,
                hops_in_other_files=1,
                ended_at=WalkEnd.REAL_LOGIC,
            ),
            id="depends-provider-that-decides",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/depends_route",
                path="app/routers/repos.py",
                function="list_repos",
                callee="get_repository",
                hops_in_file=0,
                hops_in_other_files=1,
                ended_at=WalkEnd.FORWARDS_OUTSIDE,
            ),
            id="depends-provider-that-constructs",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/unresolved_call",
                path="app/routers/invoices.py",
                function="pay_invoice",
                callee="charge_invoice",
                hops_in_file=0,
                hops_in_other_files=0,
                ended_at=WalkEnd.UNRESOLVED,
            ),
            id="unresolved-module",
        ),
        pytest.param(
            ExpectedCall(
                fixture="complexity/call_depth/library_forward.py",
                path="library_forward.py",
                function="fetch_profile",
                callee="_get",
                hops_in_file=1,
                hops_in_other_files=0,
                ended_at=WalkEnd.FORWARDS_OUTSIDE,
            ),
            id="library-forward",
        ),
    ],
)
def test_fixture_call_has_the_depth_its_rule_needs(expected: ExpectedCall) -> None:
    """Verify each fixture's call is walked to the hop counts and ending its CMPLX rule is built on."""
    call = call_in(expected)

    assert (call.hops_in_file, call.hops_in_other_files, call.ended_at) == (
        expected.hops_in_file,
        expected.hops_in_other_files,
        expected.ended_at,
    )


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param(
            ExpectedFiles(
                fixture="complexity/call_depth/cross_file_chain",
                path=ORDERS_ROUTER,
                function="create_order",
                other_files_opened=4,
            ),
            id="cross-file-chain",
        ),
        pytest.param(
            ExpectedFiles(
                fixture="complexity/call_depth/three_other_files",
                path=ORDERS_ROUTER,
                function="create_order",
                other_files_opened=3,
            ),
            id="three-other-files",
        ),
        pytest.param(
            ExpectedFiles(
                fixture="complexity/call_depth/uneven_cross_file",
                path="app/routers/checkout.py",
                function="checkout",
                other_files_opened=3,
            ),
            id="uneven-cross-file-stays-within-the-file-limit",
        ),
        pytest.param(
            ExpectedFiles(
                fixture="complexity/call_depth/depends_route",
                path="app/routers/repos.py",
                function="list_repos",
                other_files_opened=2,
            ),
            id="depends-route",
        ),
    ],
)
def test_fixture_function_opens_the_number_of_files_its_rule_needs(expected: ExpectedFiles) -> None:
    """Verify the report header counts the distinct other files the function needs opened."""
    report = CallDepthScenario(expected.fixture).report_for(expected.path, expected.function)

    assert report.other_files_opened == expected.other_files_opened


def test_unresolved_call_says_which_module_was_missing() -> None:
    """Verify the unresolved fixture fails on the absent billing module, not on something unintended."""
    call = call_in(
        ExpectedCall(
            fixture="complexity/call_depth/unresolved_call",
            path="app/routers/invoices.py",
            function="pay_invoice",
            callee="charge_invoice",
            hops_in_file=0,
            hops_in_other_files=0,
            ended_at=WalkEnd.UNRESOLVED,
        )
    )

    assert "app.billing" in call.unresolved_reason
