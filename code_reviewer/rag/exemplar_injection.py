"""
    Middleware that retrieves known-good code for the principle an agent is
    reviewing and appends it to that agent's prompt as few-shot context.
"""
import logging
from dataclasses import dataclass
from typing import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from code_reviewer.config.settings import get_settings
from code_reviewer.rag.exemplars import Exemplar, ExemplarQuery, ExemplarStore
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.shared_exemplars import SharedExemplarQuery, SharedExemplarStore
from code_reviewer.schemas.review import CodeKey

logger = logging.getLogger(__name__)

_EXEMPLAR_HEADER = """

---

For reference, here is code that already handles this principle well. It is
context, not a target: do not report incidents about it, do not require the
code under review to resemble it, and do not lower your standards because it
exists.
"""


@dataclass(frozen=True)
class ExemplarCorpora:
    """The two exemplar corpora an agent may draw on, bundled so an agent
    that already carries a rag_manager stays within the 3-parameter limit."""

    repo: ExemplarStore | None = None
    shared: SharedExemplarStore | None = None


class ExemplarInjection(AgentMiddleware):
    """Appends retrieved known-good code to an agent's prompt, drawn from the
    reviewed repo's own corpus, or from the curated repo-less one when the
    review has no repo at all — never from both."""

    def __init__(self, code_key: CodeKey, corpora: ExemplarCorpora) -> None:
        super().__init__()
        self._code_key = code_key
        self._corpora = corpora

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        exemplars = self._retrieve(request)
        if not exemplars:
            return handler(request)
        return handler(request.override(system_message=_with_exemplars(request, exemplars)))

    def _retrieve(self, request: ModelRequest) -> list[Exemplar]:
        """One corpus per review, never both. Code belonging to a repo is
        judged against how that repo already writes good code, so an empty
        repo corpus means no exemplars rather than curated ones standing in
        for a codebase they never came from. The curated corpus serves only
        reviews that have no repo to draw on."""
        code = _code_under_review(request.messages)
        if code is None:
            return []
        top_k = get_settings().exemplar_top_k
        repo_data = _repo_data(request)
        if repo_data is not None:
            return self._from_repo(repo_data, code, top_k)
        return self._from_shared(code, top_k)

    def _from_repo(self, repo_data: RepoData, code: str, top_k: int) -> list[Exemplar]:
        if self._corpora.repo is None:
            return []
        query = ExemplarQuery(
            repo_data=repo_data,
            code_key=self._code_key,
            code=code,
            relevance_floor=get_settings().exemplar_relevance_floor,
        )
        return self._safely(lambda: self._corpora.repo.find_exemplars(query, top_k=top_k))

    def _from_shared(self, code: str, top_k: int) -> list[Exemplar]:
        if self._corpora.shared is None:
            return []
        query = SharedExemplarQuery(
            code_key=self._code_key,
            code=code,
            relevance_floor=get_settings().exemplar_relevance_floor,
        )
        return self._safely(lambda: self._corpora.shared.find_exemplars(query, top_k=top_k))

    def _safely(self, lookup: Callable[[], list[Exemplar]]) -> list[Exemplar]:
        """Retrieval never fails a review: a missing corpus or a store outage
        means no exemplars, not no review."""
        try:
            return lookup()
        except Exception:
            logger.warning("Exemplar retrieval failed for %s; reviewing without it.", self._code_key)
            return []


def _repo_data(request: ModelRequest) -> RepoData | None:
    context = getattr(request.runtime, "context", None)
    if context is None:
        return None
    if getattr(context, "repo_id", None) is None or getattr(context, "owner_id", None) is None:
        return None
    return RepoData(repo_id=context.repo_id, commit_sha="", owner_id=context.owner_id)


def _code_under_review(messages: list[AnyMessage]) -> str | None:
    for message in messages:
        if isinstance(message, HumanMessage):
            return str(message.content)
    return None


def _with_exemplars(request: ModelRequest, exemplars: list[Exemplar]) -> SystemMessage:
    """Appends to the agent's rubric as an extra content block rather than
    rebuilding the message, so whatever structure the prompt already has
    survives."""
    blocks = list(request.system_message.content_blocks)
    blocks.append({"type": "text", "text": _format_exemplars(exemplars)})
    return SystemMessage(content=blocks)


def _format_exemplars(exemplars: list[Exemplar]) -> str:
    blocks = [
        f"\nExample — {exemplar.chunk_name} in {exemplar.file_path}:\n"
        f"```python\n{exemplar.code}\n```\n"
        for exemplar in exemplars
    ]
    return _EXEMPLAR_HEADER + "".join(blocks)
