"""
    Builds the code pairs a person labels as duplicate or not: this repo's own functions and classes, ranked by token overlap and sampled from three bands with a fixed seed.
"""
import argparse
import hashlib
import json
import logging
import random
import re
from collections import Counter
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FOLDERS = ("code_reviewer", "api")
EXCLUDED_FOLDERS = frozenset({"__pycache__", "alembic", ".venv"})
MIN_CHUNK_LINES = 6
MAX_USES_PER_CHUNK = 2
HIGH_BAND_RANKS = (0, 150)
MIDDLE_BAND_RANKS = (150, 1500)
LOW_BAND_RANKS = (1500, 6000)
HIGH_SHARE = 0.375
MIDDLE_SHARE = 0.375
TOKEN_PATTERN = re.compile(r"\w+")
DEFAULT_OUTPUT_FOLDER = Path(__file__).parent


class NotEnoughPairsError(Exception):
    """Raised when the bands hold fewer usable pairs than were asked for."""


class PairSide(BaseModel):
    file_path: str
    chunk_name: str
    start_line: int
    end_line: int
    code: str


class CalibrationPair(BaseModel):
    pair_id: str
    left: PairSide
    right: PairSide


class PairMeta(BaseModel):
    pair_id: str
    band: str
    similarity: float


class ScoredPair(NamedTuple):
    similarity: float
    left_index: int
    right_index: int


class PairSet(BaseModel):
    pairs: list[CalibrationPair]
    metas: list[PairMeta]


def collect_sides(root: Path) -> list[PairSide]:
    """Every long-enough top-level function and class under the source folders, in a stable order."""
    sides: list[PairSide] = []
    for folder in SOURCE_FOLDERS:
        for path in sorted((root / folder).rglob("*.py")):
            if EXCLUDED_FOLDERS.isdisjoint(path.parts):
                sides.extend(_sides_of_file(path, root))
    return sides


def rank_pairs(sides: list[PairSide]) -> list[ScoredPair]:
    """Every pair of different chunks, most similar first, leaving out pairs whose code is the same text."""
    tokens = [frozenset(TOKEN_PATTERN.findall(side.code.lower())) for side in sides]
    normalized = [_normalized(side.code) for side in sides]
    scored = [
        ScoredPair(_jaccard(tokens[left], tokens[right]), left, right)
        for left, right in combinations(range(len(sides)), 2)
        if normalized[left] != normalized[right]
    ]
    scored.sort(key=lambda row: (-row.similarity, row.left_index, row.right_index))
    return scored


def build_pair_set(sides: list[PairSide], count: int, seed: int) -> PairSet:
    """Samples count pairs across the three bands and shuffles them so the order and side give nothing away."""
    ranked = rank_pairs(sides)
    sampler = BandSampler(random.Random(seed))
    high_count = round(count * HIGH_SHARE)
    middle_count = round(count * MIDDLE_SHARE)
    chosen = [
        ("high", sampler.sample(ranked[slice(*HIGH_BAND_RANKS)], high_count)),
        ("middle", sampler.sample(ranked[slice(*MIDDLE_BAND_RANKS)], middle_count)),
        ("low", sampler.sample(ranked[slice(*LOW_BAND_RANKS)], count - high_count - middle_count)),
    ]
    labelled = [(band, row) for band, rows in chosen for row in rows]
    if len(labelled) < count:
        raise NotEnoughPairsError(f"Only {len(labelled)} pairs could be sampled for a requested {count}.")
    sampler.shuffle(labelled)
    return _to_pair_set(sides, labelled, sampler)


class BandSampler:
    """Draws pairs from a band with one random generator, never using one chunk in more than MAX_USES_PER_CHUNK pairs."""

    def __init__(self, generator: random.Random) -> None:
        self._generator = generator
        self._uses: Counter[int] = Counter()

    def sample(self, rows: list[ScoredPair], count: int) -> list[ScoredPair]:
        """Up to count pairs from rows, in random order, skipping any whose chunk is already used enough."""
        candidates = list(rows)
        self._generator.shuffle(candidates)
        picked: list[ScoredPair] = []
        for row in candidates:
            if len(picked) == count:
                break
            if self._uses[row.left_index] < MAX_USES_PER_CHUNK and self._uses[row.right_index] < MAX_USES_PER_CHUNK:
                self._uses[row.left_index] += 1
                self._uses[row.right_index] += 1
                picked.append(row)
        return picked

    def shuffle(self, items: list) -> None:
        """Shuffles in place with the same generator, so one seed decides everything."""
        self._generator.shuffle(items)

    def coin_flip(self) -> bool:
        """True or false at random, used to swap which snippet shows on the left."""
        return self._generator.random() < 0.5


def pair_id_of(first: PairSide, second: PairSide) -> str:
    """A short hash of the two code texts, the same whichever side each is on."""
    joined = "\x00".join(sorted([first.code, second.code]))
    return hashlib.sha1(joined.encode()).hexdigest()[:12]


def write_pair_set(pair_set: PairSet, folder: Path) -> None:
    """Writes pairs.json (what the labeling page loads) and pairs_meta.json (band and similarity, never shown to the labeler)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pairs.json").write_text(json.dumps([pair.model_dump() for pair in pair_set.pairs], indent=2) + "\n")
    (folder / "pairs_meta.json").write_text(json.dumps([meta.model_dump() for meta in pair_set.metas], indent=2) + "\n")


def _sides_of_file(path: Path, root: Path) -> list[PairSide]:
    try:
        chunks = PythonCodeSplit().split_code(path.read_text())
    except (CodeChunkingError, UnicodeDecodeError):
        logger.warning("Skipped %s: it could not be split", path)
        return []
    relative = path.relative_to(root).as_posix()
    return [
        PairSide(
            file_path=relative,
            chunk_name=chunk.name,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            code=chunk.code,
        )
        for chunk in chunks
        if chunk.end_line - chunk.start_line + 1 >= MIN_CHUNK_LINES
    ]


def _to_pair_set(sides: list[PairSide], labelled: list[tuple[str, ScoredPair]], sampler: BandSampler) -> PairSet:
    pairs: list[CalibrationPair] = []
    metas: list[PairMeta] = []
    for band, row in labelled:
        left, right = sides[row.left_index], sides[row.right_index]
        if sampler.coin_flip():
            left, right = right, left
        pair_id = pair_id_of(left, right)
        pairs.append(CalibrationPair(pair_id=pair_id, left=left, right=right))
        metas.append(PairMeta(pair_id=pair_id, band=band, similarity=round(row.similarity, 4)))
    return PairSet(pairs=pairs, metas=metas)


def _normalized(code: str) -> str:
    return " ".join(code.split())


def _jaccard(first: frozenset[str], second: frozenset[str]) -> float:
    union = len(first | second)
    return len(first & second) / union if union else 0.0


def _parse_arguments(arguments: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the code pairs for DRY calibration labeling.")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_FOLDER)
    return parser.parse_args(None if arguments is None else list(arguments))


def main() -> None:
    """Command line entry point: collects chunks, samples the pairs and writes both files."""
    arguments = _parse_arguments()
    sides = collect_sides(REPO_ROOT)
    pair_set = build_pair_set(sides, arguments.count, arguments.seed)
    write_pair_set(pair_set, arguments.out_dir)
    bands = Counter(meta.band for meta in pair_set.metas)
    print(f"{len(sides)} chunks, wrote {len(pair_set.pairs)} pairs to {arguments.out_dir} ({dict(bands)})")


if __name__ == "__main__":
    main()
