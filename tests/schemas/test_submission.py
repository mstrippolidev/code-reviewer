import pytest
from pydantic import ValidationError

from code_reviewer.schemas.submission import SubmittedFile


def test_submitted_file_accepts_path_and_content() -> None:
    file = SubmittedFile(file_path="app/service.py", content="print('hi')\n")

    assert file.file_path == "app/service.py"
    assert file.content == "print('hi')\n"


def test_submitted_file_requires_both_fields() -> None:
    with pytest.raises(ValidationError):
        SubmittedFile(file_path="app/service.py")
