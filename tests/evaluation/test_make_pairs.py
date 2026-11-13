"""
    Tests that the calibration pair builder is deterministic, respects its bands and chunk-use cap, and never leaks a score into pairs.json.
"""
from collections import Counter
from pathlib import Path

import pytest

from evaluation.calibration import make_pairs
from evaluation.calibration.make_pairs import (
    NotEnoughPairsError,
    PairSide,
    build_pair_set,
    collect_sides,
    pair_id_of,
    write_pair_set,
)

FUNCTION_COUNT = 40


def _function_source(index: int) -> str:
    shared = "\n".join(f"    step_{line} = value + {line}" for line in range(index % 5 + 4))
    return f"def function_{index}(value: int) -> int:\n{shared}\n    return value * {index}\n"


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    folder = tmp_path / "api"
    folder.mkdir()
    for file_index in range(4):
        body = "\n".join(_function_source(file_index * 10 + offset) for offset in range(10))
        (folder / f"module_{file_index}.py").write_text(body)
    return tmp_path


@pytest.fixture
def small_bands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(make_pairs, "HIGH_BAND_RANKS", (0, 100))
    monkeypatch.setattr(make_pairs, "MIDDLE_BAND_RANKS", (100, 400))
    monkeypatch.setattr(make_pairs, "LOW_BAND_RANKS", (400, 780))


def test_the_same_seed_gives_the_same_pairs(repo_root: Path, small_bands: None) -> None:
    """Verify a re-run is reproducible, so the labels always refer to the same pair ids."""
    sides = collect_sides(repo_root)

    first = build_pair_set(sides, 20, seed=7)
    second = build_pair_set(sides, 20, seed=7)

    assert [pair.pair_id for pair in first.pairs] == [pair.pair_id for pair in second.pairs]


def test_a_different_seed_gives_different_pairs(repo_root: Path, small_bands: None) -> None:
    """Verify the seed actually drives the sampling."""
    sides = collect_sides(repo_root)

    first = build_pair_set(sides, 20, seed=7)
    second = build_pair_set(sides, 20, seed=8)

    assert [pair.pair_id for pair in first.pairs] != [pair.pair_id for pair in second.pairs]


def test_the_requested_count_is_returned_across_all_three_bands(repo_root: Path, small_bands: None) -> None:
    """Verify the bands add up to the count and each one is present."""
    pair_set = build_pair_set(collect_sides(repo_root), 20, seed=7)

    assert len(pair_set.pairs) == 20
    assert set(Counter(meta.band for meta in pair_set.metas)) == {"high", "middle", "low"}


def test_no_chunk_appears_in_more_pairs_than_the_cap(repo_root: Path, small_bands: None) -> None:
    """Verify one chunk cannot dominate the labeling set."""
    pair_set = build_pair_set(collect_sides(repo_root), 20, seed=7)

    uses = Counter(
        (side.file_path, side.chunk_name) for pair in pair_set.pairs for side in (pair.left, pair.right)
    )

    assert max(uses.values()) <= make_pairs.MAX_USES_PER_CHUNK


def test_chunks_shorter_than_the_minimum_are_dropped(tmp_path: Path) -> None:
    """Verify tiny functions never become a side of a pair."""
    folder = tmp_path / "api"
    folder.mkdir()
    (folder / "short.py").write_text("def tiny() -> int:\n    return 1\n")

    assert collect_sides(tmp_path) == []


def test_excluded_folders_are_skipped(tmp_path: Path) -> None:
    """Verify migrations are not offered as duplicates of each other."""
    migrations = tmp_path / "api" / "alembic"
    migrations.mkdir(parents=True)
    (migrations / "0001.py").write_text(_function_source(1))

    assert collect_sides(tmp_path) == []


def test_pair_id_does_not_depend_on_which_side_is_left() -> None:
    """Verify swapping the sides keeps the id, since the page swaps them at random."""
    first = PairSide(file_path="a.py", chunk_name="a", start_line=1, end_line=9, code="one")
    second = PairSide(file_path="b.py", chunk_name="b", start_line=1, end_line=9, code="two")

    assert pair_id_of(first, second) == pair_id_of(second, first)


def test_asking_for_more_pairs_than_exist_raises(repo_root: Path, small_bands: None) -> None:
    """Verify an underfilled sample fails loudly instead of silently handing back fewer pairs."""
    with pytest.raises(NotEnoughPairsError):
        build_pair_set(collect_sides(repo_root), 500, seed=7)


def test_pairs_json_has_no_score_or_band(repo_root: Path, small_bands: None, tmp_path: Path) -> None:
    """Verify what the labeling page loads carries nothing that could anchor the label."""
    pair_set = build_pair_set(collect_sides(repo_root), 10, seed=7)
    output = tmp_path / "out"

    write_pair_set(pair_set, output)

    pairs_text = (output / "pairs.json").read_text()
    assert "similarity" not in pairs_text and "band" not in pairs_text
    assert "similarity" in (output / "pairs_meta.json").read_text()
