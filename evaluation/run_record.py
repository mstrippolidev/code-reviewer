"""
    The conditions under which an evaluation report was produced.
"""
import hashlib
import subprocess

from pydantic import BaseModel

PROMPT_HASH_LENGTH = 12


class RunRecord(BaseModel):
    git_commit: str
    git_dirty: bool
    prompt_hash_by_agent: dict[str, str]

    def only(self, agent: str) -> "RunRecord":
        """The same record narrowed to one agent, for a per-agent report file."""
        return self.model_copy(update={"prompt_hash_by_agent": {agent: self.prompt_hash_by_agent[agent]}})


def hash_prompt(prompt: str) -> str:
    """A short stable fingerprint of a system prompt's text."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:PROMPT_HASH_LENGTH]


def build_run_record(prompt_hash_by_agent: dict[str, str]) -> RunRecord:
    """The record for a run happening now, from the current git state."""
    return RunRecord(
        git_commit=_git("rev-parse", "--short", "HEAD"),
        git_dirty=bool(_git("status", "--porcelain")),
        prompt_hash_by_agent=prompt_hash_by_agent,
    )


def _git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], capture_output=True, text=True, check=True).stdout.strip()
