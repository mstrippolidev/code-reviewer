"""
    Dispatch wiring for a review restricted to a subset of agents — both
    dispatch strategies, fakes only.
"""
from dataclasses import replace

import pytest
from sqlalchemy import create_engine

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.pipeline.dispatch import review_file_runnable
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, ReviewScope, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from tests.pipeline.test_dispatch import (
    DISPATCH_FUNCTIONS,
    DispatchFn,
    FakeAgent,
    FakeCodeSimilarityIndex,
    FakeDryJudge,
    FakeEmbeddingIndex,
    FakeRerankPostprocessor,
)

ALL_FAKE_KEYS = (
    CodeKey.COH,
    CodeKey.CMPLX,
    CodeKey.COUP,
    CodeKey.ARCH,
    CodeKey.VAR,
    CodeKey.ERR,
    CodeKey.CONC,
    CodeKey.TCASE,
)


@pytest.fixture
def agents() -> dict[CodeKey, FakeAgent]:
    return {code_key: FakeAgent(code_key) for code_key in ALL_FAKE_KEYS}


@pytest.fixture
def container(agents: dict[CodeKey, FakeAgent]) -> AgentsContainer:
    return AgentsContainer(
        file_agents=[agents[CodeKey.COH], agents[CodeKey.CMPLX]],
        chunk_agents=[agents[CodeKey.VAR], agents[CodeKey.ERR], agents[CodeKey.CONC]],
        tcase_agent=agents[CodeKey.TCASE],
        dry_judge=FakeDryJudge(),
        rag_manager=FakeEmbeddingIndex(),
        structural_hash_store=StructuralHashStore(engine=create_engine("sqlite:///:memory:"), schema_name=None),
        code_similarity_index=FakeCodeSimilarityIndex(),
        history_match_reranker=HistoryMatchReranker(max_candidates=5, postprocessor=FakeRerankPostprocessor()),
        coupling_agent_repoless=agents[CodeKey.COUP],
        architecture_agent_repoless=agents[CodeKey.ARCH],
    )


def _prepared_file(
    review_scope: ReviewScope = ReviewScope.FULL, repo_data: RepoData | None = None
) -> PreparedFile:
    return PreparedFile(
        source_file=SubmittedFile(file_path="f.py", content="def foo():\n    return 1\n"),
        size_status=SizeStatus.NORMAL,
        review_scope=review_scope,
        repo_data=repo_data,
    )


def _codes(entries: list[AgentReviewEntry]) -> set[CodeKey]:
    return {entry.code_key for entry in entries}


@DISPATCH_FUNCTIONS
def test_without_a_selection_every_agent_runs(dispatch: DispatchFn, container: AgentsContainer) -> None:
    """Verify that leaving the selection unset keeps the full roster, DRY included."""
    entries = dispatch(_prepared_file(), container.restricted_to(None))

    assert _codes(entries) == {*ALL_FAKE_KEYS, CodeKey.DRY}


@DISPATCH_FUNCTIONS
def test_a_selected_file_agent_is_the_only_one_that_runs(dispatch: DispatchFn, container: AgentsContainer) -> None:
    """Verify that unselected file, chunk, TCASE and DRY agents all stay out of the result."""
    entries = dispatch(_prepared_file(), container.restricted_to(frozenset({CodeKey.COH})))

    assert _codes(entries) == {CodeKey.COH}


@DISPATCH_FUNCTIONS
def test_a_selected_chunk_agent_is_the_only_one_that_runs(dispatch: DispatchFn, container: AgentsContainer) -> None:
    """Verify that chunk agents are filtered by the selection like file agents are."""
    entries = dispatch(_prepared_file(), container.restricted_to(frozenset({CodeKey.VAR})))

    assert _codes(entries) == {CodeKey.VAR}


@DISPATCH_FUNCTIONS
def test_an_unselected_tcase_agent_is_never_called(
    dispatch: DispatchFn, container: AgentsContainer, agents: dict[CodeKey, FakeAgent]
) -> None:
    """Verify that TCASE is not run, so its pairing lookups and model call are never paid for."""
    dispatch(_prepared_file(), container.restricted_to(frozenset({CodeKey.COH})))

    assert agents[CodeKey.TCASE].execute_agent_calls == []


@DISPATCH_FUNCTIONS
def test_a_selected_tcase_agent_runs_alone(dispatch: DispatchFn, container: AgentsContainer) -> None:
    """Verify that TCASE can be requested on its own."""
    entries = dispatch(_prepared_file(), container.restricted_to(frozenset({CodeKey.TCASE})))

    assert _codes(entries) == {CodeKey.TCASE}


@DISPATCH_FUNCTIONS
def test_a_selected_dry_agent_runs_alone(dispatch: DispatchFn, container: AgentsContainer) -> None:
    """Verify that DRY can be requested on its own and still reports its repoless skip."""
    entries = dispatch(_prepared_file(), container.restricted_to(frozenset({CodeKey.DRY})))

    assert _codes(entries) == {CodeKey.DRY}


@DISPATCH_FUNCTIONS
def test_the_repoless_coupling_variant_respects_the_selection(
    dispatch: DispatchFn, container: AgentsContainer
) -> None:
    """Verify that COUP and ARCH, which are built as variants outside the file agents list, are filtered too."""
    entries = dispatch(_prepared_file(), container.restricted_to(frozenset({CodeKey.COUP})))

    assert _codes(entries) == {CodeKey.COUP}


@DISPATCH_FUNCTIONS
def test_the_repo_aware_coupling_variant_respects_the_selection(
    dispatch: DispatchFn, container: AgentsContainer, agents: dict[CodeKey, FakeAgent]
) -> None:
    """Verify that a repo review runs the repo-aware COUP when selected and never the repoless one."""
    repo_aware_coupling = FakeAgent(CodeKey.COUP)
    repo_container = replace(container, coupling_agent=repo_aware_coupling).restricted_to(frozenset({CodeKey.COUP}))
    repo_data = RepoData(repo_id="10", owner_id="99", commit_sha="abc123")

    dispatch(_prepared_file(repo_data=repo_data), repo_container)

    repoless_coupling = agents[CodeKey.COUP]
    assert (len(repo_aware_coupling.execute_agent_calls), len(repoless_coupling.execute_agent_calls)) == (1, 0)


@DISPATCH_FUNCTIONS
def test_a_standalone_test_file_runs_only_the_selected_hygiene_agents_and_tcase(
    dispatch: DispatchFn, container: AgentsContainer
) -> None:
    """Verify that a selection mixing applicable and inapplicable agents keeps only those the file's scope allows."""
    selection = frozenset({CodeKey.VAR, CodeKey.TCASE, CodeKey.COH})

    entries = dispatch(_prepared_file(ReviewScope.TEST_FILE_STANDALONE), container.restricted_to(selection))

    assert _codes(entries) == {CodeKey.VAR, CodeKey.TCASE}


@DISPATCH_FUNCTIONS
def test_a_standalone_test_file_skips_a_selected_non_hygiene_chunk_agent(
    dispatch: DispatchFn, container: AgentsContainer
) -> None:
    """Verify that selecting a production-code chunk agent like CONC cannot widen a test file's hygiene-only scope."""
    selection = frozenset({CodeKey.VAR, CodeKey.CONC})

    entries = dispatch(_prepared_file(ReviewScope.TEST_FILE_STANDALONE), container.restricted_to(selection))

    assert _codes(entries) == {CodeKey.VAR}


@pytest.mark.asyncio
async def test_on_agent_reviewed_fires_only_for_the_selected_agents(container: AgentsContainer) -> None:
    """Verify that live progress never reports an agent the review was not asked to run."""
    reported: list[CodeKey] = []

    async def on_agent_reviewed(code_key: CodeKey, entry: AgentReviewEntry) -> None:
        reported.append(code_key)

    selection = frozenset({CodeKey.COH, CodeKey.TCASE})
    await review_file_runnable(_prepared_file(), container.restricted_to(selection), on_agent_reviewed=on_agent_reviewed)

    assert set(reported) == {CodeKey.COH, CodeKey.TCASE}


@DISPATCH_FUNCTIONS
def test_a_selection_naming_no_agent_that_applies_yields_no_entries(
    dispatch: DispatchFn, container: AgentsContainer
) -> None:
    """Verify that a standalone test file with only a production-code agent selected is an empty review, not a crash."""
    entries = dispatch(_prepared_file(ReviewScope.TEST_FILE_STANDALONE), container.restricted_to(frozenset({CodeKey.COH})))

    assert entries == []


def test_restricting_a_container_leaves_the_original_unrestricted(container: AgentsContainer) -> None:
    """Verify that the container built once at startup is never narrowed by one request's selection."""
    container.restricted_to(frozenset({CodeKey.COH}))

    assert container.selected_keys is None


def test_restricting_a_container_shares_the_built_agents(container: AgentsContainer) -> None:
    """Verify that the copy reuses the already-built agents instead of rebuilding them."""
    restricted = container.restricted_to(frozenset({CodeKey.COH}))

    assert restricted.file_agents is container.file_agents
