"""
    Command line: python -m api.exemplars.seed
"""
import logging

from api.config.settings import get_api_settings
from api.logging_config import configure_logging
from code_reviewer.rag.embedding.factory import build_embedding
from code_reviewer.rag.exemplar_seeding import SEED_EXEMPLARS_DIR, seed_shared_exemplars
from code_reviewer.rag.shared_exemplars import SharedExemplarStore

logger = logging.getLogger(__name__)


def main() -> None:
    """Seeds the repo-less exemplar corpus once and logs how many files it loaded."""
    configure_logging(get_api_settings())
    store = SharedExemplarStore(embedding=build_embedding())
    loaded = seed_shared_exemplars(store, SEED_EXEMPLARS_DIR)
    logger.info("Seeded %d shared exemplar files.", loaded)


if __name__ == "__main__":
    main()
