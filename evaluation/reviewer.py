"""
    Runs one labelled fixture through its agent the way a review would: CMPLX
    with its call-depth reports, TCASE with its source and test file, every
    other agent with the file alone.
"""
from pydantic import BaseModel

from code_reviewer.agents.architecture import ArchitectureAgent
from code_reviewer.agents.base import AgentBase, FileReviewMeta
from code_reviewer.agents.boundaries import BoundariesAgent
from code_reviewer.agents.cohesion import CohesionAgent
from code_reviewer.agents.comments import CommentsAgent
from code_reviewer.agents.complexity import ComplexityAgent
from code_reviewer.agents.concurrency import ConcurrencyAgent
from code_reviewer.agents.coupling import CouplingAgent
from code_reviewer.agents.coverage_gap import CoverageGapAgent
from code_reviewer.agents.errors import ErrorsAgent
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.naming import NamingAgent
from code_reviewer.agents.solid_1 import SolidSrpOcpAgent
from code_reviewer.agents.solid_2 import SolidLspDipAgent
from code_reviewer.agents.testability import TestabilityAgent
from code_reviewer.schemas.paired import Pairing
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey
from code_reviewer.schemas.submission import SubmittedFile
from code_reviewer.telemetry.run_transcript import capture_transcript
from evaluation.incidents import count_invalid_lines
from evaluation.labels import FixtureLabel
from evaluation.transcript import RunTranscript, transcript_of
from tests.call_depth_scenario import CallDepthScenario
from tests.helpers import FIXTURES_DIR, load_fixture

COMPLEXITY_FOLDER = "complexity"
COVERAGE_GAP_FOLDER = "tcase"

AGENT_CLASS_BY_FOLDER: dict[str, type[AgentBase]] = {
    "arch": ArchitectureAgent,
    "bound": BoundariesAgent,
    "coh": CohesionAgent,
    "comments": CommentsAgent,
    "conc": ConcurrencyAgent,
    "coup": CouplingAgent,
    "errors": ErrorsAgent,
    "naming": NamingAgent,
    "solid1": SolidSrpOcpAgent,
    "solid2": SolidLspDipAgent,
    "test": TestabilityAgent,
    COMPLEXITY_FOLDER: ComplexityAgent,
    COVERAGE_GAP_FOLDER: CoverageGapAgent,
}


CODE_KEY_BY_FOLDER: dict[str, CodeKey] = {
    "arch": CodeKey.ARCH,
    "bound": CodeKey.BOUND,
    "coh": CodeKey.COH,
    "comments": CodeKey.CMT,
    "conc": CodeKey.CONC,
    "coup": CodeKey.COUP,
    "errors": CodeKey.ERR,
    "naming": CodeKey.VAR,
    "solid1": CodeKey.SOLID1,
    "solid2": CodeKey.SOLID2,
    "test": CodeKey.TEST,
    COMPLEXITY_FOLDER: CodeKey.CMPLX,
    COVERAGE_GAP_FOLDER: CodeKey.TCASE,
}


def production_llm_for(folder: str, llm: LLMInterface) -> LLMInterface:
    """The model production gives this folder's agent: the registry's own routing, fast tier included."""
    return llm.for_code_key(CODE_KEY_BY_FOLDER[folder])


def pairing_of(label: FixtureLabel) -> Pairing:
    """The source file of a TCASE label with its test file, when it has one."""
    source_file = SubmittedFile(file_path=label.path, content=load_fixture(label.fixture))
    test_files = []
    if label.paired_test_fixture:
        test_name = (FIXTURES_DIR / label.paired_test_fixture).name
        test_files.append(SubmittedFile(file_path=test_name, content=load_fixture(label.paired_test_fixture)))
    return Pairing(source_file=source_file, test_files=test_files)


class ReviewedRun(BaseModel):
    entry: AgentReviewEntry
    invalid_line_incidents: int
    transcript: RunTranscript


class LabelReviewer:
    def __init__(self, folder: str, llm: LLMInterface) -> None:
        self._folder = folder
        self._agent = AGENT_CLASS_BY_FOLDER[folder](llm=production_llm_for(folder, llm))

    def review_run(self, label: FixtureLabel) -> ReviewedRun:
        """One review of the label's fixture, with a count of incidents pointing outside the file and what the model said."""
        with capture_transcript() as messages:
            entry = self.review(label)
        return ReviewedRun(
            entry=entry,
            invalid_line_incidents=count_invalid_lines(entry, self._line_count(label)),
            transcript=transcript_of(messages),
        )

    def _line_count(self, label: FixtureLabel) -> int:
        if self._folder == COMPLEXITY_FOLDER:
            return len(CallDepthScenario(label.fixture).code(label.path).splitlines())
        return len(load_fixture(label.fixture).splitlines())

    def review(self, label: FixtureLabel) -> AgentReviewEntry:
        """Run the label's fixture through the agent and return the agent's entry."""
        if self._folder == COMPLEXITY_FOLDER:
            return self._review_with_call_depth_reports(label)
        if self._folder == COVERAGE_GAP_FOLDER:
            return self._agent.execute_agent(pairing_of(label).get_content(), file_path=label.path).review[0]
        return self._agent.execute_agent(load_fixture(label.fixture), file_path=label.path).review[0]

    def _review_with_call_depth_reports(self, label: FixtureLabel) -> AgentReviewEntry:
        scenario = CallDepthScenario(label.fixture)
        meta = FileReviewMeta(call_depth_reports=scenario.reports_for(label.path))
        return self._agent.execute_agent(scenario.code(label.path), label.path, meta).review[0]
