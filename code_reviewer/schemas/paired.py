"""
    Pairs a source file with the test files submitted alongside it, so
    TCASE can read both.
"""
from pydantic import BaseModel, Field

from code_reviewer.schemas.submission import SubmittedFile


class Pairing(BaseModel):
    """A source file paired with its submitted test files, if any."""

    source_file: SubmittedFile = Field(description="The source file under review.")
    test_files: list[SubmittedFile] = Field(
        description="Test files paired with the source file; empty if none were submitted."
    )

    def get_content(self) -> str:
        """Combines the source and test file contents into one prompt string for TCASE."""
        return (
            "SOURCE FILE:\n"
            f"{self.source_file.content}\n\n"
            "TEST FILES CONTENT:\n"
            f"{self._test_files_content()}"
        )

    def _test_files_content(self) -> str:
        if not self.test_files:
            return "No test file was submitted for this source file."
        return "\n\n".join(test_file.content for test_file in self.test_files)
