"""
    Pure length check on raw submitted content. Runs before the Guardrails
    intake screen so pathologically long input (e.g. a single 500,000
    character minified line) never reaches an LLM call.
"""
from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.errors import SubmissionTooLargeError


def run_raw_character_guard(content: str) -> None:
    """Rejects content whose raw character length exceeds the configured cap."""
    max_characters = get_settings().max_submission_characters
    if len(content) > max_characters:
        raise SubmissionTooLargeError(
            f"Submission is {len(content)} characters, exceeding the "
            f"{max_characters} character limit."
        )
