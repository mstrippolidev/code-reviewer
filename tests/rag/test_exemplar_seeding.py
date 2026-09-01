"""
    Tests for seeding the repo-less corpus from hand-curated fixtures.
"""
from pathlib import Path

import pytest

from code_reviewer.rag.exemplar_seeding import FIXTURE_DIR_CODE_KEYS, seed_shared_exemplars
from code_reviewer.rag.exemplars import ExemplarSource
from code_reviewer.schemas.review import CodeKey


class RecordingStore:
    def __init__(self, empty: bool = True) -> None:
        self.added: list[tuple[CodeKey, ExemplarSource]] = []
        self._empty = empty

    def is_empty(self) -> bool:
        return self._empty

    def add_exemplar(self, code_key: CodeKey, source: ExemplarSource) -> None:
        self.added.append((code_key, source))


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    (tmp_path / "solid1").mkdir()
    (tmp_path / "solid1" / "good_solid1.py").write_text("class A: ...")
    (tmp_path / "coh").mkdir()
    (tmp_path / "coh" / "good_cohesion.py").write_text("def f(): ...")
    (tmp_path / "coh" / "bad_cohesion.py").write_text("def g(): ...")
    (tmp_path / "errors").mkdir()
    (tmp_path / "errors" / "good_error_handling.py").write_text("def h(): ...")
    return tmp_path


def test_only_good_fixtures_are_loaded(fixtures_dir: Path) -> None:
    """Verify violation fixtures never enter the corpus — only files written
    to demonstrate a principle belong there."""
    store = RecordingStore()

    seed_shared_exemplars(store, fixtures_dir)

    assert {source.file_path for _, source in store.added} == {"good_cohesion.py", "good_solid1.py"}


def test_each_fixture_is_tagged_with_its_directorys_agent(fixtures_dir: Path) -> None:
    """Verify a fixture is stored under the principle it demonstrates, so
    retrieval filtering on code_key returns the right corpus."""
    store = RecordingStore()

    seed_shared_exemplars(store, fixtures_dir)

    assert dict((key, source.file_path) for key, source in store.added) == {
        CodeKey.COH: "good_cohesion.py",
        CodeKey.SOLID1: "good_solid1.py",
    }


def test_fixtures_for_agents_that_never_retrieve_are_skipped(fixtures_dir: Path) -> None:
    """Verify a good fixture outside the retrieving tier is not stored. Only
    the 2.0-weight agents read the corpus, so anything else would be a row
    nothing can ever return."""
    store = RecordingStore()

    seed_shared_exemplars(store, fixtures_dir)

    assert CodeKey.ERR not in {key for key, _ in store.added}


def test_seeded_directories_match_the_agents_that_retrieve() -> None:
    """Verify the fixture map tracks exactly the agents wired for injection.
    TEST is deliberately absent despite its 2.0 weight: it judges whether
    code can be tested rather than how it is written, so a good-code example
    teaches it nothing. If injection moves, seeding has to move with it or
    the corpus drifts out of step with what can be read."""
    assert set(FIXTURE_DIR_CODE_KEYS.values()) == {
        CodeKey.SOLID1,
        CodeKey.SOLID2,
        CodeKey.COH,
        CodeKey.COUP,
    }


def test_missing_directories_are_skipped(tmp_path: Path) -> None:
    """Verify agents with no curated fixture do not fail the seed run."""
    store = RecordingStore()

    assert seed_shared_exemplars(store, tmp_path) == 0


def test_every_fixture_directory_maps_to_a_real_agent() -> None:
    """Verify the directory map cannot silently reference a removed agent."""
    assert set(FIXTURE_DIR_CODE_KEYS.values()) <= set(CodeKey)


def test_an_already_populated_corpus_is_left_alone(fixtures_dir: Path) -> None:
    """Verify the bootstrap runs only once. These fixtures demonstrate a
    principle to a test suite, so they seed an empty corpus rather than
    accumulating alongside deliberately curated entries."""
    store = RecordingStore(empty=False)

    assert seed_shared_exemplars(store, fixtures_dir) == 0
    assert store.added == []
