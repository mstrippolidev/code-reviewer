"""
    Integration tests for CMPLX's call-depth rules: each fixture is walked by
    the real CallDepthReportBuilder and the report reaches a real model
    through ComplexityAgent, the way dispatch hands it over in a review.
    tests/pipeline/call_depth/test_cmplx_fixture_reports.py pins what each
    fixture's report says.
"""
import pytest
from pydantic import BaseModel

from code_reviewer.agents.base import FileReviewMeta
from code_reviewer.agents.complexity import ComplexityAgent
from code_reviewer.pipeline.line_offset import parse_line_range
from code_reviewer.schemas.review import AgentReviewEntry, Incident, Priority
from tests.call_depth_scenario import CallDepthScenario

pytestmark = pytest.mark.llm

ORDERS_ROUTER = "app/routers/orders.py"

PRIORITY_RANK = {Priority.LOW: 1, Priority.MEDIUM: 2, Priority.HIGH: 3, Priority.CRITICAL: 4}


class Case(BaseModel):
    fixture: str
    path: str
    expected: Priority | None
    also_accepted: list[Priority | None] = []

    @property
    def accepted(self) -> list[Priority | None]:
        return [self.expected, *self.also_accepted]


class LineCase(BaseModel):
    fixture: str
    path: str
    function: str
    callee: str
    priority: Priority


@pytest.fixture
def complexity_agent(small_llm) -> ComplexityAgent:
    return ComplexityAgent(llm=small_llm)


def review_with_report(agent: ComplexityAgent, fixture: str, path: str) -> AgentReviewEntry:
    scenario = CallDepthScenario(fixture)
    meta = FileReviewMeta(call_depth_reports=scenario.reports_for(path))
    return agent.execute_agent(scenario.code(path), path, meta).review[0]


def highest_priority(entry: AgentReviewEntry) -> Priority | None:
    return max((incident.priority for incident in entry.incidents), key=PRIORITY_RANK.get, default=None)


def incidents_at(entry: AgentReviewEntry, priority: Priority) -> list[Incident]:
    return [incident for incident in entry.incidents if incident.priority == priority]


def call_line(case: LineCase) -> int:
    report = CallDepthScenario(case.fixture).report_for(case.path, case.function)
    return next(call.line for call in report.calls if call.callee == case.callee)


def covers(incident: Incident, line: int) -> bool:
    start, end = parse_line_range(incident.line_position)
    return start <= line <= end


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            Case(fixture="complexity/call_depth/cross_file_chain", path=ORDERS_ROUTER, expected=Priority.HIGH),
            id="more-than-3-other-files-is-high",
        ),
        pytest.param(
            Case(fixture="complexity/call_depth/mixed_chain", path=ORDERS_ROUTER, expected=Priority.HIGH),
            id="mixed-chain-judges-files-first",
        ),
        pytest.param(
            Case(
                fixture="complexity/false_positive_same_file_helpers_within_limit.py",
                path="false_positive_same_file_helpers_within_limit.py",
                expected=None,
                also_accepted=[Priority.LOW, Priority.MEDIUM],
            ),
            id="five-same-file-hops-is-never-high",
        ),
        pytest.param(
            Case(
                fixture="complexity/hops_priority_medium.py",
                path="hops_priority_medium.py",
                expected=Priority.MEDIUM,
                also_accepted=[Priority.HIGH],
            ),
            id="six-same-file-hops-is-at-least-medium",
        ),
        pytest.param(
            Case(
                fixture="complexity/hops_pass_through_chain.py",
                path="hops_pass_through_chain.py",
                expected=Priority.HIGH,
            ),
            id="more-than-7-same-file-hops-is-high",
        ),
        pytest.param(
            Case(
                fixture="complexity/call_depth/hop_limit_chain.py",
                path="hop_limit_chain.py",
                expected=Priority.HIGH,
            ),
            id="walk-stopped-at-the-hop-limit-is-high",
        ),
        pytest.param(
            Case(fixture="complexity/uneven_call_depth.py", path="uneven_call_depth.py", expected=Priority.MEDIUM),
            id="uneven-same-file-depth-is-medium",
        ),
        pytest.param(
            Case(
                fixture="complexity/call_depth/uneven_cross_file",
                path="app/routers/checkout.py",
                expected=Priority.MEDIUM,
            ),
            id="uneven-cross-file-depth-is-medium",
        ),
        pytest.param(
            Case(
                fixture="complexity/false_positive_even_call_depth.py",
                path="false_positive_even_call_depth.py",
                expected=None,
            ),
            id="even-depth-is-not-flagged",
        ),
        pytest.param(
            Case(fixture="complexity/call_depth/deciding_layers", path=ORDERS_ROUTER, expected=None),
            id="layer-that-decides-is-not-flagged",
        ),
        pytest.param(
            Case(fixture="complexity/call_depth/depends_route", path="app/routers/repos.py", expected=None),
            id="depends-providers-are-not-flagged",
        ),
        pytest.param(
            Case(fixture="complexity/call_depth/unresolved_call", path="app/routers/invoices.py", expected=None),
            id="unresolved-call-is-not-flagged",
        ),
    ],
)
def test_highest_priority_follows_the_call_depth_rule(complexity_agent: ComplexityAgent, case: Case) -> None:
    """Verify the most severe incident CMPLX reports is one the fixture's call-depth rule accepts.

    None means no incidents at all: the report must not turn a clean file
    into a flagged one.
    """
    entry = review_with_report(complexity_agent, case.fixture, case.path)

    assert highest_priority(entry) in case.accepted


def test_three_other_files_is_not_high(complexity_agent: ComplexityAgent) -> None:
    """Verify exactly 3 other files stays below high: the limit is more than 3.

    Two of those hops are pass-throughs into other files, which the prompt
    allows reporting below high, so only high is ruled out.
    """
    entry = review_with_report(complexity_agent, "complexity/call_depth/three_other_files", ORDERS_ROUTER)

    assert highest_priority(entry) not in {Priority.HIGH, Priority.CRITICAL}


def test_wrapper_at_a_library_boundary_is_at_most_low(complexity_agent: ComplexityAgent) -> None:
    """Verify a one-hop wrapper whose walk ends at a library is never above low.

    The wrapper only forwards, so a low note is defensible; one hop is far
    inside every limit, so anything higher would be a false alarm.
    """
    entry = review_with_report(complexity_agent, "complexity/call_depth/library_forward.py", "library_forward.py")

    assert highest_priority(entry) in {None, Priority.LOW}


def test_route_without_a_report_is_not_flagged_for_hops_it_cannot_see(complexity_agent: ComplexityAgent) -> None:
    """Verify the four-file route is clean when no report comes with it.

    The same code is high with its report; without one, the model sees a
    single imported call and must not guess at files it was not shown.
    """
    scenario = CallDepthScenario("complexity/call_depth/cross_file_chain")

    entry = complexity_agent.execute_agent(scenario.code(ORDERS_ROUTER), ORDERS_ROUTER).review[0]

    assert entry.incidents == []


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            LineCase(
                fixture="complexity/call_depth/cross_file_chain",
                path=ORDERS_ROUTER,
                function="create_order",
                callee="place_order",
                priority=Priority.HIGH,
            ),
            id="cross-file-chain",
        ),
        pytest.param(
            LineCase(
                fixture="complexity/uneven_call_depth.py",
                path="uneven_call_depth.py",
                function="price_for",
                callee="discount_entry",
                priority=Priority.MEDIUM,
            ),
            id="uneven-same-file",
        ),
        pytest.param(
            LineCase(
                fixture="complexity/call_depth/uneven_cross_file",
                path="app/routers/checkout.py",
                function="checkout",
                callee="ship_cart",
                priority=Priority.MEDIUM,
            ),
            id="uneven-cross-file",
        ),
    ],
)
def test_hop_incident_covers_the_call_line_from_the_report(complexity_agent: ComplexityAgent, case: LineCase) -> None:
    """Verify a hop or uneven-depth incident points at the call the report names, not somewhere else in the file."""
    entry = review_with_report(complexity_agent, case.fixture, case.path)

    assert any(covers(incident, call_line(case)) for incident in incidents_at(entry, case.priority))
