"""
    Tests for ExemplarStore's scoping rules, which decide what a review can
    ever see. The vector store is faked so no embedding call happens here.
"""
import pytest

from code_reviewer.rag.errors import RepoOwnerRequiredError
from code_reviewer.rag.exemplars import ExemplarSource, ExemplarStore
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import CodeKey


def _store_without_dependencies() -> ExemplarStore:
    store = ExemplarStore.__new__(ExemplarStore)
    return store


def test_adding_an_exemplar_without_an_owner_is_rejected() -> None:
    """Verify unowned code never enters the corpus, since retrieval scopes
    on owner_id and an unowned entry could never be scoped back out."""
    store = _store_without_dependencies()
    repo_data = RepoData(repo_id="r1", commit_sha="abc", owner_id=None)

    with pytest.raises(RepoOwnerRequiredError):
        store.add_exemplar(repo_data, CodeKey.SOLID1, ExemplarSource("a.py", "class A: ..."))


def test_retrieval_without_an_owner_is_rejected() -> None:
    """Verify a lookup missing owner_id raises rather than quietly widening
    to every owner of that repo_id."""
    store = _store_without_dependencies()
    repo_data = RepoData(repo_id="r1", commit_sha="abc", owner_id=None)

    with pytest.raises(RepoOwnerRequiredError):
        store._scope_filters(repo_data, CodeKey.SOLID1)


def test_scope_filters_cover_repo_owner_and_principle() -> None:
    """Verify every retrieval is narrowed on all three axes, so one repo
    cannot see another's exemplars and SOLID1 cannot see SOLID2's."""
    store = _store_without_dependencies()
    repo_data = RepoData(repo_id="r1", commit_sha="abc", owner_id="o1")

    filters = store._scope_filters(repo_data, CodeKey.SOLID1)

    assert {(f.key, f.value) for f in filters.filters} == {
        ("repo_id", "r1"),
        ("owner_id", "o1"),
        ("code_key", "SOLID1"),
    }
