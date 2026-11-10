"""
    A readable account, for one agent, of what the model answered on each label it did not pass every run,
    and a separate log holding the model's reasoning on those runs.
"""
from code_reviewer.schemas.review import Incident, Priority
from evaluation.scoring import EvaluationReport, LabelResult
from evaluation.transcript import RunTranscript, TranscriptMessage

TOOL_RESULT_LIMIT = 600


def render_transcript_report(report: EvaluationReport, reasoning_log_name: str) -> str:
    """Markdown for a single-agent report: one section per label below a full pass, without the reasoning text."""
    agent, results = next(iter(report.results.items()))
    weak = _weak_results(results)
    lines = [
        f"# {agent}: transcripts of labels below 100%",
        "",
        f"Model: {report.model_by_agent[agent]}. {report.runs_per_label} runs per label. Created {report.created_at:%Y-%m-%d %H:%M} UTC.",
        "",
        f"The model's reasoning is not in this file; it is in {reasoning_log_name}, in the model's logs folder.",
        "",
    ]
    if not weak:
        lines.append("Every label passed on every run.")
    for result in weak:
        lines += _label_section(result)
    return "\n".join(lines) + "\n"


def render_reasoning_log(report: EvaluationReport) -> str:
    """Plain text of the reasoning the model sent on every run of each label below a full pass."""
    agent, results = next(iter(report.results.items()))
    lines = [f"{agent}: reasoning on labels below 100%", ""]
    for result in _weak_results(results):
        for index, transcript in enumerate(result.transcripts_per_run):
            lines += [f"=== {result.label.id} / run {index + 1} ===", "", *_reasoning_lines(transcript)]
    return "\n".join(lines) + "\n"


def _weak_results(results: list[LabelResult]) -> list[LabelResult]:
    return [result for result in results if result.accepted_rate < 1]


def _reasoning_lines(transcript: RunTranscript) -> list[str]:
    reasonings = [message.reasoning for message in transcript.messages if message.reasoning]
    if not reasonings:
        return ["(no reasoning sent)", ""]
    return [line for reasoning in reasonings for line in (reasoning, "")]


def _label_section(result: LabelResult) -> list[str]:
    label = result.label
    accepted = ", ".join(priority.value if priority else "clean" for priority in label.accepted)
    lines = [
        f"## {label.id}",
        "",
        f"- passed {result.accepted_rate:.0%} of {result.total_runs} runs",
        f"- expected: {label.expected.value if label.expected else 'clean'}; accepted: {accepted}",
        f"- label reason: {label.reason}",
        "",
    ]
    for index, highest in enumerate(result.highest_per_run):
        lines += _run_section(result, index, highest)
    for failure in result.failures:
        lines += ["### run failed", "", failure, ""]
    return lines


def _run_section(result: LabelResult, index: int, highest: Priority | None) -> list[str]:
    missed = " (MISSED)" if highest not in result.label.accepted else ""
    outside = " (ANSWER NOT ABOUT THIS FILE?)" if _invalid_lines_of_run(result, index) else ""
    answer = highest.value if highest else "none"
    lines = [f"### run {index + 1}: answered {answer}{missed}{outside}", ""]
    lines += _incident_lines(result.incidents_per_run[index])
    transcript = result.transcripts_per_run[index] if index < len(result.transcripts_per_run) else None
    return lines + _transcript_lines(transcript)


def _invalid_lines_of_run(result: LabelResult, index: int) -> int:
    """Incidents of this run pointing outside the file; 0 for a report saved before this was recorded per run."""
    per_run = result.invalid_lines_per_run
    return per_run[index] if index < len(per_run) else 0


def _incident_lines(incidents: list[Incident]) -> list[str]:
    if not incidents:
        return ["Incidents: none", ""]
    return ["Incidents:", *[f"- [{item.priority.value}] {item.line_position}: {item.description}" for item in incidents], ""]


def _transcript_lines(transcript: RunTranscript | None) -> list[str]:
    if transcript is None:
        return ["No transcript was recorded for this run.", ""]
    if not transcript.has_reasoning:
        return ["The model sent no reasoning on this run.", "", *_message_lines(transcript.messages)]
    return _message_lines(transcript.messages)


def _message_lines(messages: list[TranscriptMessage]) -> list[str]:
    lines: list[str] = []
    for message in messages:
        if message.role in ("user", "system"):
            continue
        lines += _single_message_lines(message)
    return lines


def _single_message_lines(message: TranscriptMessage) -> list[str]:
    lines: list[str] = []
    if message.reasoning_characters:
        lines += [f"Reasoning: {message.reasoning_characters} characters, in the reasoning log.", ""]
    if message.reply_details:
        lines += [f"Reply: {_reply_details_text(message.reply_details)}", ""]
    if message.role == "tool":
        lines += [f"Tool result ({message.tool_name}): {message.text[:TOOL_RESULT_LIMIT]}", ""]
    for call in message.tool_calls:
        lines += [f"Tool call: {call.name} {call.arguments}", ""]
    if message.role == "assistant" and message.text:
        lines += ["Said:", "", "~~~~", message.text, "~~~~", ""]
    return lines


def _reply_details_text(details: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in details.items())
