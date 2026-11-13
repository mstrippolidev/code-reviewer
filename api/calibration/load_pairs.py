"""
    Command line: python -m api.calibration.load_pairs evaluation/calibration/pairs.json
"""
import argparse
import asyncio
from pathlib import Path

from api.calibration.pair_loader import load_pairs, read_pair_records
from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine


async def _run(path: Path) -> int:
    engine = DatabaseEngine(get_api_settings().async_database_url)
    try:
        async with engine.new_session() as session:
            return await load_pairs(session, read_pair_records(path))
    finally:
        await engine.dispose()


def main() -> None:
    """Loads the given pairs file and prints how many pairs were new."""
    parser = argparse.ArgumentParser(description="Load calibration pairs into the database.")
    parser.add_argument("pairs_file", type=Path)
    added = asyncio.run(_run(parser.parse_args().pairs_file))
    print(f"Added {added} pairs.")


if __name__ == "__main__":
    main()
