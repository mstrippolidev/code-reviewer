"""
    Integration tests for CMPLX, driven by the labels in
    tests/fixtures/complexity/labels.json. Each fixture is walked by the real
    CallDepthReportBuilder and the report reaches a real model through
    ComplexityAgent, the way dispatch hands it over in a review.
    tests/pipeline/call_depth/test_cmplx_fixture_reports.py pins what each
    fixture's report says.
"""
import pytest

from code_reviewer.agents.base import FileReviewMeta
from code_reviewer.agents.complexity import ComplexityAgent
from code_reviewer.pipeline.line_offset import parse_line_range
from code_reviewer.schemas.review import AgentReviewEntry, Incident, Priority
from evaluation.incidents import highest_priority
from evaluation.labels import FixtureLabel, load_labels
from tests.call_depth_scenario import CallDepthScenario

pytestmark = pytest.mark.llm

ORDERS_ROUTER = "app/routers/orders.py"

LABELS = load_labels("complexity")
LABELS_WITH_A_CALL_LINE = [label for label in LABELS if label.must_cover_call]


@pytest.fixture
def complexity_agent(small_llm) -> ComplexityAgent:
    return ComplexityAgent(llm=small_llm)


def review_with_report(agent: ComplexityAgent, fixture: str, path: str) -> AgentReviewEntry:
    scenario = CallDepthScenario(fixture)
    meta = FileReviewMeta(call_depth_reports=scenario.reports_for(path))
    return agent.execute_agent(scenario.code(path), path, meta).review[0]


def incidents_at(entry: AgentReviewEntry, priority: Priority) -> list[Incident]:
    return [incident for incident in entry.incidents if incident.priority == priority]


def call_line(label: FixtureLabel) -> int:
    reference = label.must_cover_call
    report = CallDepthScenario(label.fixture).report_for(label.path, reference.function)
    return next(call.line for call in report.calls if call.callee == reference.callee)


def covers(incident: Incident, line: int) -> bool:
    start, end = parse_line_range(incident.line_position)
    return start <= line <= end


@pytest.mark.parametrize("label", LABELS, ids=lambda label: label.id)
def test_highest_priority_follows_the_label(complexity_agent: ComplexityAgent, label: FixtureLabel) -> None:
    """Verify the most severe incident CMPLX reports is one the fixture's label accepts.

    None means no incidents at all: a clean file must not come back flagged.
    """
    entry = review_with_report(complexity_agent, label.fixture, label.path)

    assert highest_priority(entry) in label.accepted


def test_route_without_a_report_is_not_flagged_for_hops_it_cannot_see(complexity_agent: ComplexityAgent) -> None:
    """Verify the four-file route is clean when no report comes with it.

    The same code is high with its report; without one, the model sees a
    single imported call and must not guess at files it was not shown.
    """
    scenario = CallDepthScenario("complexity/call_depth/cross_file_chain")

    entry = complexity_agent.execute_agent(scenario.code(ORDERS_ROUTER), ORDERS_ROUTER).review[0]

    assert entry.incidents == []


@pytest.mark.parametrize("label", LABELS_WITH_A_CALL_LINE, ids=lambda label: label.id)
def test_hop_incident_covers_the_call_line_from_the_report(complexity_agent: ComplexityAgent, label: FixtureLabel) -> None:
    """Verify a hop or uneven-depth incident points at the call the report names, not somewhere else in the file."""
    entry = review_with_report(complexity_agent, label.fixture, label.path)

    assert any(covers(incident, call_line(label)) for incident in incidents_at(entry, label.expected))
