"""
    Tests for the run record: prompt fingerprints and git state, with git faked.
"""
import pytest

from evaluation import run_record
from evaluation.run_record import RunRecord, build_run_record, hash_prompt


def test_the_same_prompt_always_has_the_same_hash() -> None:
    """Verify a fingerprint is stable, so two runs of an unchanged prompt can be told apart from an edited one."""
    assert hash_prompt("review naming") == hash_prompt("review naming")


def test_an_edited_prompt_has_a_different_hash() -> None:
    """Verify changing one character of the prompt changes its fingerprint."""
    assert hash_prompt("review naming") != hash_prompt("review naming.")


def test_the_record_can_be_narrowed_to_one_agent() -> None:
    """Verify the per-agent report file keeps only its own agent's prompt hash."""
    record = RunRecord(git_commit="abc1234", git_dirty=False, prompt_hash_by_agent={"bound": "h1", "tcase": "h2"})

    assert record.only("bound").prompt_hash_by_agent == {"bound": "h1"}


def test_a_new_record_reads_the_current_git_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the commit and the uncommitted-changes flag come from git."""
    answers = {("rev-parse", "--short", "HEAD"): "abc1234", ("status", "--porcelain"): " M file.py"}
    monkeypatch.setattr(run_record, "_git", lambda *arguments: answers[arguments])

    record = build_run_record({"bound": "h1"})

    assert (record.git_commit, record.git_dirty) == ("abc1234", True)


def test_a_clean_tree_is_not_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify empty `git status` output means no uncommitted changes."""
    answers = {("rev-parse", "--short", "HEAD"): "abc1234", ("status", "--porcelain"): ""}
    monkeypatch.setattr(run_record, "_git", lambda *arguments: answers[arguments])

    assert not build_run_record({}).git_dirty
