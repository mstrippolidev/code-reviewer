"""
    Loads hand-curated good-code files into the repo-less exemplar corpus.

    Scoped to the agents that retrieve exemplars: storing any other
    principle's would leave rows nothing can ever read.
"""
import logging
from pathlib import Path

from code_reviewer.rag.exemplars import ExemplarSource
from code_reviewer.rag.shared_exemplars import SharedExemplarStore
from code_reviewer.schemas.review import CodeKey

logger = logging.getLogger(__name__)

FIXTURE_DIR_CODE_KEYS: dict[str, CodeKey] = {
    "solid1": CodeKey.SOLID1,
    "solid2": CodeKey.SOLID2,
    "coh": CodeKey.COH,
    "coup": CodeKey.COUP,
}

GOOD_FIXTURE_GLOB = "good_*.py"


def seed_shared_exemplars(store: SharedExemplarStore, fixtures_dir: Path) -> int:
    """Bootstrap the repo-less corpus from hand-curated good_*.py fixtures.

    Only ever writes to the repo-less corpus, and only while it is still
    empty. These fixtures were written to demonstrate a principle to a test
    suite, so they are a starting point for a corpus with nothing in it, not
    something to keep adding alongside curated entries.

    Args:
        store: The repo-less corpus to bootstrap.
        fixtures_dir: Directory holding one subdirectory per agent, named by
            the keys of FIXTURE_DIR_CODE_KEYS.

    Returns:
        How many files were loaded, or 0 if the corpus already held
        something. Directories with no good_*.py file are skipped rather
        than failing the run, since not every agent has one.

    Raises:
        VectorStoreQueryError: If the corpus cannot be inspected.
    """
    if not store.is_empty():
        logger.info("Shared exemplar corpus is already populated; skipping fixture bootstrap.")
        return 0
    loaded = 0
    for directory, code_key in FIXTURE_DIR_CODE_KEYS.items():
        for path in sorted((fixtures_dir / directory).glob(GOOD_FIXTURE_GLOB)):
            store.add_exemplar(code_key, ExemplarSource(str(path.name), path.read_text()))
            loaded += 1
    if loaded == 0:
        logger.warning("No good_*.py fixtures found under %s", fixtures_dir)
    return loaded
