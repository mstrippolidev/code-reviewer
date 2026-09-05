"""
    Tests for SizeGuardedDryJudge's own logic: which query/candidate pairs
    reach DryJudge untouched, how an oversized side gets split and re-
    judged, how split-piece incidents are offset back to the original
    chunk's coordinates, and how the recursion depth cap degrades to a
    flagged incident. DryJudge itself is faked so these exercise the size
    guard only, never a real LLM.
"""
from code_reviewer.rag.dry_judge import JudgeCandidate
from code_reviewer.rag.dry_judge_split import SizeGuardedDryJudge, SplitConfig
from code_reviewer.schemas.review import Incident, Priority

_SMALL_CONFIG = SplitConfig(max_pair_chars=20, overlap_chars=5)


class FakeDryJudge:
    def __init__(self, incidents: list[Incident] | None = None) -> None:
        self._incidents = incidents if incidents is not None else []
        self.judge_calls: list[tuple[str, list[JudgeCandidate]]] = []

    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]:
        self.judge_calls.append((query_code, list(candidates)))
        return list(self._incidents)


def _incident(line_position: str = "1-1", priority: Priority = Priority.MEDIUM) -> Incident:
    return Incident(priority=priority, line_position=line_position, description="d", advice="a")


def test_pair_within_the_size_limit_reaches_the_batched_judge_call() -> None:
    """Both sides fit under max_pair_chars, so the whole batch is judged in
    one call, with no splitting."""
    fake_judge = FakeDryJudge(incidents=[_incident()])
    candidate = JudgeCandidate(location="a.py:f", code="short")
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    incidents = guard.judge("query", [candidate])

    assert fake_judge.judge_calls == [("query", [candidate])]
    assert incidents == [_incident()]


def test_normal_and_oversized_candidates_are_partitioned_into_separate_calls() -> None:
    """A batch mixing a normal-sized and an oversized candidate must send
    only the normal one through the single shared batch call."""
    fake_judge = FakeDryJudge()
    normal = JudgeCandidate(location="a.py:f", code="short")
    oversized = JudgeCandidate(location="b.py:g", code="x" * 100)
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    guard.judge("query", [normal, oversized])

    assert fake_judge.judge_calls[0][1] == [normal]


def test_no_safe_candidates_skips_the_batched_judge_call() -> None:
    """Every candidate is oversized, so the shared batch call (which would
    otherwise run with an empty candidate list) must never happen."""
    fake_judge = FakeDryJudge()
    oversized = JudgeCandidate(location="b.py:g", code="x" * 100)
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    guard.judge("query", [oversized])

    assert all(candidates for _, candidates in fake_judge.judge_calls)


def test_oversized_query_is_split_and_each_piece_is_judged_against_the_untouched_candidate() -> None:
    """The query side alone exceeds the limit — it must be split into
    overlapping pieces, each judged against the full, untouched candidate."""
    fake_judge = FakeDryJudge()
    candidate = JudgeCandidate(location="a.py:f", code="short")
    oversized_query = "line one\nline two\nline three\nline four\n"
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    guard.judge(oversized_query, [candidate])

    assert len(fake_judge.judge_calls) > 1
    assert all(candidates == [candidate] for _, candidates in fake_judge.judge_calls)


def test_oversized_query_split_incidents_are_offset_to_the_original_query_coordinates() -> None:
    """A piece starting at line 3 of the original query reports line 1 in
    its own frame — the guard must offset that back to line 3."""
    oversized_query = "aaaaaaaaaa\nbbbbbbbbbb\nccccccccccccccccccccccccccc\n"
    fake_judge = FakeDryJudge(incidents=[_incident(line_position="1-1")])
    candidate = JudgeCandidate(location="a.py:f", code="short")
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    incidents = guard.judge(oversized_query, [candidate])

    assert any(incident.line_position != "1-1" for incident in incidents)


def test_oversized_candidate_is_split_and_each_piece_is_judged_against_the_untouched_query() -> None:
    """The candidate side alone exceeds the limit — it must be split into
    overlapping pieces, each judged against the full, untouched query."""
    fake_judge = FakeDryJudge()
    oversized_candidate = JudgeCandidate(
        location="a.py:f", code="line one\nline two\nline three\nline four\n"
    )
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    guard.judge("short query", [oversized_candidate])

    assert len(fake_judge.judge_calls) > 1
    assert all(query_code == "short query" for query_code, _ in fake_judge.judge_calls)


def test_oversized_candidate_split_incidents_keep_the_original_location() -> None:
    """Splitting a candidate's code must not change its reported location —
    only the code sent to the judge changes, never the identity of the
    candidate a confirmed duplicate is attributed to."""
    oversized_candidate = JudgeCandidate(
        location="a.py:f", code="line one\nline two\nline three\nline four\n"
    )
    fake_judge = FakeDryJudge()
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    guard.judge("short query", [oversized_candidate])

    assert all(candidates[0].location == "a.py:f" for _, candidates in fake_judge.judge_calls)


def test_oversized_candidate_split_incidents_are_not_offset() -> None:
    """A judge verdict's line_position is always relative to the query, not
    the candidate, so splitting the candidate must return incidents
    unchanged from what the fake judge returned."""
    oversized_candidate = JudgeCandidate(
        location="a.py:f", code="line one\nline two\nline three\nline four\n"
    )
    fake_judge = FakeDryJudge(incidents=[_incident(line_position="1-1")])
    guard = SizeGuardedDryJudge(fake_judge, _SMALL_CONFIG)

    incidents = guard.judge("short query", [oversized_candidate])

    assert all(incident.line_position == "1-1" for incident in incidents)


def test_pair_still_oversized_past_the_recursion_depth_cap_is_flagged_unreviewed() -> None:
    """Both sides stay oversized no matter how far they're split — past the
    depth cap this must degrade to a flagged incident instead of looping
    or silently dropping the pair."""
    huge_code = "x" * 500
    candidate = JudgeCandidate(location="a.py:f", code=huge_code)
    fake_judge = FakeDryJudge()
    tiny_config = SplitConfig(max_pair_chars=5, overlap_chars=1)
    guard = SizeGuardedDryJudge(fake_judge, tiny_config)

    incidents = guard.judge(huge_code, [candidate])

    assert fake_judge.judge_calls == []
    assert all(incident.priority == Priority.LOW for incident in incidents)


def test_pair_still_oversized_past_the_recursion_depth_cap_names_the_candidate() -> None:
    """The flagged incident must point back at which candidate went
    unreviewed, since nothing else in the merged result says so."""
    huge_code = "x" * 500
    candidate = JudgeCandidate(location="legacy/aggregates.py:total", code=huge_code)
    fake_judge = FakeDryJudge()
    tiny_config = SplitConfig(max_pair_chars=5, overlap_chars=1)
    guard = SizeGuardedDryJudge(fake_judge, tiny_config)

    incidents = guard.judge(huge_code, [candidate])

    assert "legacy/aggregates.py:total" in incidents[0].description
