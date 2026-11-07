"""
    The Grafana files are checked without Docker: they parse, they are consistent with each other, and every
    metric they query is one the code defines. Whether Grafana loads them is checked against a running stack.
"""
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from api.observability import kafka_metrics as api_kafka_metrics
from api.observability import metrics as api_metrics_module
from api.observability.kafka_metrics import KafkaMetrics
from api.observability.llm_cost import LlmCostMetrics
from api.observability.metrics import ApiMetrics
from code_reviewer.telemetry import metrics as pipeline_metrics_module
from code_reviewer.telemetry import rag_metrics as rag_metrics_module
from code_reviewer.telemetry.metrics import REVIEW_COST_BUCKETS_USD, PipelineMetrics
from code_reviewer.telemetry.rag_metrics import RagMetrics

GRAFANA = Path(__file__).resolve().parents[2] / "observability" / "grafana"
PROVISIONING = GRAFANA / "provisioning"
DASHBOARDS = sorted((GRAFANA / "dashboards").glob("*.json"))
HTTP_METRICS_FROM_THE_FASTAPI_INSTRUMENTATION = {
    "http_server_duration_milliseconds_bucket",
    "http_server_duration_milliseconds_count",
    "http_server_duration_milliseconds_sum",
}
UID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
METRIC_TOKEN = re.compile(r"\b((?:code_reviewer|http_server)_[A-Za-z0-9_]+)\b")
_UNIT_NAMES = {"s": "seconds", "ms": "milliseconds"}


class RecordingMeter:
    """Records the instruments the code asks for, so their Prometheus names can be derived without exporting."""

    def __init__(self) -> None:
        self.instruments: list[tuple[str, str, str]] = []

    def create_counter(self, name: str, unit: str = "", **_: Any) -> Mock:
        return self._record(name, unit, "counter")

    def create_histogram(self, name: str, unit: str = "", **_: Any) -> Mock:
        return self._record(name, unit, "histogram")

    def create_up_down_counter(self, name: str, unit: str = "", **_: Any) -> Mock:
        return self._record(name, unit, "gauge")

    def create_observable_gauge(self, name: str, unit: str = "", **_: Any) -> Mock:
        return self._record(name, unit, "gauge")

    def _record(self, name: str, unit: str, kind: str) -> Mock:
        self.instruments.append((name, unit, kind))
        return Mock()


def _prometheus_names(name: str, unit: str, kind: str) -> list[str]:
    """OpenTelemetry to Prometheus naming, as confirmed against the Collector's output:
    dots become underscores, a plain unit is appended (s as seconds), {braced} units are dropped,
    counters end in _total and histograms in _bucket, _count and _sum."""
    base = name.replace(".", "_")
    unit_part = "" if not unit or unit.startswith("{") else _UNIT_NAMES.get(unit, unit)
    full = f"{base}_{unit_part}" if unit_part else base
    return {
        "counter": [f"{full}_total"],
        "histogram": [f"{full}_bucket", f"{full}_count", f"{full}_sum"],
        "gauge": [full],
    }[kind]


class _PricedModels:
    def price_of(self, model_name: str) -> Any:
        raise NotImplementedError


def _defined_metric_names() -> set[str]:
    meter = RecordingMeter()
    PipelineMetrics(meter)
    RagMetrics(meter)
    ApiMetrics(meter)
    KafkaMetrics(meter)
    LlmCostMetrics(meter, _PricedModels())
    names = {name for instrument in meter.instruments for name in _prometheus_names(*instrument)}
    return names | HTTP_METRICS_FROM_THE_FASTAPI_INSTRUMENTATION


def _label_names() -> set[str]:
    """Every label key the metrics modules define, written the way Prometheus spells them."""
    modules = (pipeline_metrics_module, rag_metrics_module, api_metrics_module, api_kafka_metrics)
    keys = {
        value
        for module in modules
        for value in vars(module).values()
        if isinstance(value, str) and value.startswith("code_reviewer.")
    }
    return {key.replace(".", "_") for key in keys}


def _dashboard_expressions() -> list[tuple[str, str]]:
    expressions = []
    for path in DASHBOARDS:
        for panel in json.loads(path.read_text())["panels"]:
            for target in panel["targets"]:
                expressions.append((f"{path.stem}: {panel['title']}", target["expr"]))
    return expressions


def _rules() -> list[dict[str, Any]]:
    document = yaml.safe_load((PROVISIONING / "alerting" / "rules.yml").read_text())
    return [rule for group in document["groups"] for rule in group["rules"]]


def _metrics_used_in(expression: str) -> set[str]:
    return set(METRIC_TOKEN.findall(expression)) - _label_names()


def _balanced(expression: str) -> bool:
    depth = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    for character in expression:
        if character in depth:
            depth[character] += 1
        elif character in closing:
            depth[closing[character]] -= 1
            if depth[closing[character]] < 0:
                return False
    return not any(depth.values())


def test_there_are_dashboards_to_check() -> None:
    """Verify the glob found the files, so the checks below cannot pass over an empty list."""
    assert len(DASHBOARDS) == 5


def test_every_dashboard_has_a_unique_uid_that_matches_its_file_name_and_a_unique_title() -> None:
    """Verify provisioning cannot silently overwrite one dashboard with another."""
    documents = [json.loads(path.read_text()) for path in DASHBOARDS]

    assert [document["uid"] for document in documents] == [path.stem for path in DASHBOARDS]
    assert len({document["title"] for document in documents}) == len(documents)


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda path: path.stem)
def test_every_panel_has_a_title_a_position_and_at_least_one_query(path: Path) -> None:
    """Verify no panel is an empty box."""
    for panel in json.loads(path.read_text())["panels"]:
        assert panel["title"] and panel["gridPos"]["w"] > 0 and panel["targets"]


@pytest.mark.parametrize("label,expression", _dashboard_expressions(), ids=lambda value: value[:60])
def test_every_dashboard_query_is_non_empty_and_has_balanced_brackets(label: str, expression: str) -> None:
    """Verify the cheapest class of query typo; the running Prometheus checks the rest."""
    assert expression.strip() and _balanced(expression)


@pytest.mark.parametrize("label,expression", _dashboard_expressions(), ids=lambda value: value[:60])
def test_every_metric_a_dashboard_queries_is_defined_by_the_code(label: str, expression: str) -> None:
    """Verify a panel cannot point at a metric that no instrument produces, which would stay empty forever."""
    assert _metrics_used_in(expression) <= _defined_metric_names()


def test_rule_uids_are_valid_and_unique() -> None:
    """Verify Grafana's identifier limits (40 characters, letters, digits, - and _) and no duplicates."""
    uids = [rule["uid"] for rule in _rules()]

    assert all(UID_PATTERN.match(uid) for uid in uids) and len(set(uids)) == len(uids)


def test_each_rule_names_a_condition_that_is_one_of_its_own_queries() -> None:
    """Verify the step that decides firing exists in the rule."""
    for rule in _rules():
        assert rule["condition"] in {step["refId"] for step in rule["data"]}


def test_each_rule_queries_the_provisioned_prometheus_data_source() -> None:
    """Verify the rules point at the uid the data source file really sets."""
    datasource = yaml.safe_load((PROVISIONING / "datasources" / "prometheus.yml").read_text())["datasources"][0]

    for rule in _rules():
        assert rule["data"][0]["datasourceUid"] == datasource["uid"]


@pytest.mark.parametrize("rule", _rules(), ids=lambda rule: rule["uid"])
def test_every_metric_a_rule_queries_is_defined_by_the_code(rule: dict[str, Any]) -> None:
    """Verify an alert cannot watch a metric that never exists, which would never fire and never say so."""
    expression = rule["data"][0]["model"]["expr"]

    assert _balanced(expression) and _metrics_used_in(expression) <= _defined_metric_names()


def test_silence_does_not_fire_a_rule() -> None:
    """Verify a missing series means "not firing", as every rule's query is a filter that returns nothing when fine."""
    assert {rule["noDataState"] for rule in _rules()} == {"OK"}


def test_the_expensive_review_rule_reads_a_real_review_cost_bucket() -> None:
    """Verify the le label in the rule is one of the histogram's bucket bounds, written the way Prometheus prints it."""
    rule = next(rule for rule in _rules() if rule["uid"] == "expensive-review")
    bounds = set(re.findall(r'le="([^"]+)"', rule["data"][0]["model"]["expr"]))

    assert bounds == {"5.0"} and 5 in REVIEW_COST_BUCKETS_USD


def test_the_cost_dashboard_reads_the_same_bucket_as_the_rule() -> None:
    """Verify the dashboard's "above 5 USD" panel and the alert cannot drift apart."""
    expressions = " ".join(expression for label, expression in _dashboard_expressions() if label.startswith("cost"))

    assert 'le="5.0"' in expressions


def test_no_credential_is_in_a_file_grafana_loads() -> None:
    """Verify the provisioning folder holds no AWS key or secret; the SNS example is kept outside it."""
    text = " ".join(path.read_text() for path in PROVISIONING.rglob("*.yml"))

    assert not re.search(r"AKIA[0-9A-Z]{12,}|secret_key|access_key|secretAccessKey", text)


def test_the_sns_example_is_not_loaded_by_grafana() -> None:
    """Verify a placeholder topic cannot become a live contact point by accident."""
    assert (GRAFANA / "alerting-sns.example.yml").exists()
    assert not list(PROVISIONING.rglob("*sns*"))
