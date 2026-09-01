"""
    Tests for ExemplarInjection's own plumbing: when it queries the corpus,
    what it does to the prompt, and how it degrades. The store is faked, so
    no embedding or LLM call happens here.
"""
import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from code_reviewer.agents.base import ReviewContext
from code_reviewer.rag.exemplar_injection import ExemplarCorpora, ExemplarInjection
from code_reviewer.rag.exemplars import Exemplar, ExemplarQuery
from code_reviewer.rag.shared_exemplars import SharedExemplarQuery
from code_reviewer.schemas.review import CodeKey

BASE_PROMPT = "REVIEW SRP AND OCP."


class FakeStore:
    """Stand-in for ExemplarStore, recording the query it was asked."""

    def __init__(self, exemplars: list[Exemplar] | None = None, error: Exception | None = None) -> None:
        self._exemplars = exemplars or []
        self._error = error
        self.query: ExemplarQuery | None = None

    def find_exemplars(self, query: ExemplarQuery, top_k: int = 3) -> list[Exemplar]:
        self.query = query
        if self._error is not None:
            raise self._error
        return self._exemplars


def _exemplar() -> Exemplar:
    return Exemplar(
        code_key=CodeKey.SOLID1,
        file_path="billing/invoice.py",
        chunk_name="InvoiceTotals",
        code="class InvoiceTotals:\n    ...",
        score=0.81,
    )


class _Runtime:
    def __init__(self, context: ReviewContext | None) -> None:
        self.context = context


def _request(context: ReviewContext | None = ReviewContext(repo_id="r1", owner_id="o1")) -> ModelRequest:
    return ModelRequest(
        model=None,
        messages=[HumanMessage(content="class Billing: ..."), AIMessage(content="x")],
        system_prompt=BASE_PROMPT,
        runtime=_Runtime(context),
    )


def _capture_prompt(middleware: ExemplarInjection, request: ModelRequest) -> str:
    seen = {}

    def handler(final_request: ModelRequest) -> str:
        seen["prompt"] = final_request.system_message.text
        return "response"

    middleware.wrap_model_call(request, handler)
    return seen["prompt"]


def test_retrieved_exemplar_is_appended_to_the_prompt() -> None:
    """Verify a relevant exemplar's code reaches the agent's system prompt."""
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=FakeStore([_exemplar()])))

    prompt = _capture_prompt(middleware, _request())

    assert "class InvoiceTotals:" in prompt


def test_original_prompt_is_preserved_when_injecting() -> None:
    """Verify injection appends to the agent's rubric rather than replacing it."""
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=FakeStore([_exemplar()])))

    prompt = _capture_prompt(middleware, _request())

    assert prompt.startswith(BASE_PROMPT)


def test_no_exemplars_leaves_the_prompt_untouched() -> None:
    """Verify an empty corpus injects nothing — a weak match steers judgment
    worse than no match, so silence is the correct fallback."""
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=FakeStore([])))

    prompt = _capture_prompt(middleware, _request())

    assert prompt == BASE_PROMPT


def test_store_failure_leaves_the_prompt_untouched() -> None:
    """Verify a corpus outage degrades to a normal review instead of
    failing it — exemplars are an enhancement, never a dependency."""
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=FakeStore(error=RuntimeError("store down"))))

    prompt = _capture_prompt(middleware, _request())

    assert prompt == BASE_PROMPT


def test_review_without_repo_context_skips_retrieval() -> None:
    """Verify a standalone review with no repo scoping never queries the
    corpus, since exemplars are per-repo and there is no repo to scope to."""
    store = FakeStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=store))

    prompt = _capture_prompt(middleware, _request(context=None))

    assert prompt == BASE_PROMPT
    assert store.query is None


def test_query_carries_the_agents_own_code_key() -> None:
    """Verify the lookup is filtered to this agent's principle, so a SOLID1
    exemplar can never be injected into SOLID2's prompt."""
    store = FakeStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID2, ExemplarCorpora(repo=store))

    _capture_prompt(middleware, _request())

    assert store.query.code_key == CodeKey.SOLID2


def test_query_carries_the_code_under_review() -> None:
    """Verify the corpus is searched against the file being reviewed rather
    than against the agent's prompt."""
    store = FakeStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=store))

    _capture_prompt(middleware, _request())

    assert store.query.code == "class Billing: ..."


def test_query_carries_the_repo_scoping_from_context() -> None:
    """Verify retrieval is scoped to the reviewing repo, never across tenants."""
    store = FakeStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=store))

    _capture_prompt(middleware, _request())

    assert (store.query.repo_data.repo_id, store.query.repo_data.owner_id) == ("r1", "o1")


def test_review_without_owner_scoping_skips_retrieval() -> None:
    """Verify a context carrying a repo but no owner never queries the
    corpus. Exemplars are stored per owner, so an unowned lookup would
    otherwise match a co-owner's entries on a shared public repo."""
    store = FakeStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=store))

    prompt = _capture_prompt(middleware, _request(context=ReviewContext(repo_id="r1", owner_id=None)))

    assert prompt == BASE_PROMPT
    assert store.query is None


class FakeSharedStore:
    """Stand-in for SharedExemplarStore, recording what it was asked."""

    def __init__(self, exemplars: list[Exemplar] | None = None) -> None:
        self._exemplars = exemplars or []
        self.query: SharedExemplarQuery | None = None
        self.top_k: int | None = None

    def find_exemplars(self, query: SharedExemplarQuery, top_k: int = 3) -> list[Exemplar]:
        self.query = query
        self.top_k = top_k
        return self._exemplars


def test_empty_repo_corpus_does_not_fall_back_to_the_curated_one() -> None:
    """Verify a repo with nothing stored gets no exemplars at all. Curated
    code comes from a different codebase, so standing it in for this repo's
    own conventions would misrepresent what good looks like here."""
    shared = FakeSharedStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=FakeStore([]), shared=shared))

    prompt = _capture_prompt(middleware, _request())

    assert prompt == BASE_PROMPT
    assert shared.query is None


def test_standalone_review_still_reaches_the_shared_corpus() -> None:
    """Verify a review with no repo context skips the repo corpus but still
    reads the repo-less one, which has nothing to scope."""
    shared = FakeSharedStore([_exemplar()])
    repo_store = FakeStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=repo_store, shared=shared))

    prompt = _capture_prompt(middleware, _request(context=None))

    assert "class InvoiceTotals:" in prompt
    assert repo_store.query is None


def test_a_repo_review_never_mixes_in_curated_exemplars() -> None:
    """Verify a prompt is never built from both corpora at once, so every
    example an agent sees comes from one consistent source."""
    shared = FakeSharedStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=FakeStore([_exemplar()]), shared=shared))

    _capture_prompt(middleware, _request())

    assert shared.query is None


def test_standalone_review_never_queries_the_repo_corpus() -> None:
    """Verify a review with no repo reads only the curated corpus — an
    unscoped repo lookup would reach another owner's exemplars."""
    repo_store = FakeStore([_exemplar()])
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=repo_store, shared=FakeSharedStore([_exemplar()])))

    _capture_prompt(middleware, _request(context=None))

    assert repo_store.query is None
