"""
    Finds the labels that did not pass every run in earlier reports, so only those are run again.
"""
import json
from pathlib import Path

from pydantic import TypeAdapter

from evaluation.scoring import LabelResult

RESULTS_BY_AGENT = TypeAdapter(dict[str, list[LabelResult]])


def weak_label_ids(report_paths: list[Path]) -> dict[str, list[str]]:
    """Label ids per agent whose latest result is below 100%; a later report replaces an earlier result for the same label."""
    latest: dict[tuple[str, str], LabelResult] = {}
    for path in sorted(report_paths):
        results_by_agent = RESULTS_BY_AGENT.validate_python(json.loads(path.read_text())["results"])
        for agent, results in results_by_agent.items():
            latest.update({(agent, result.label.id): result for result in results})
    weak: dict[str, list[str]] = {}
    for (agent, label_id), result in latest.items():
        if result.accepted_rate < 1:
            weak.setdefault(agent, []).append(label_id)
    return weak
