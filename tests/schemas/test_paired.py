from code_reviewer.schemas.paired import Pairing
from code_reviewer.schemas.submission import SubmittedFile


def test_get_content_combines_source_and_test_file_content() -> None:
    pairing = Pairing(
        source_file=SubmittedFile(file_path="login.py", content="def login(): ..."),
        test_files=[SubmittedFile(file_path="test_login.py", content="def test_login(): ...")],
    )

    content = pairing.get_content()

    assert "def login(): ..." in content
    assert "def test_login(): ..." in content


def test_get_content_states_plainly_when_no_test_file_was_submitted() -> None:
    pairing = Pairing(
        source_file=SubmittedFile(file_path="login.py", content="def login(): ..."),
        test_files=[],
    )

    content = pairing.get_content()

    assert "No test file was submitted for this source file." in content


def test_get_content_joins_multiple_test_files() -> None:
    pairing = Pairing(
        source_file=SubmittedFile(file_path="login.py", content="def login(): ..."),
        test_files=[
            SubmittedFile(file_path="tests/unit/test_login.py", content="def test_unit(): ..."),
            SubmittedFile(file_path="tests/integration/test_login.py", content="def test_integ(): ..."),
        ],
    )

    content = pairing.get_content()

    assert "def test_unit(): ..." in content
    assert "def test_integ(): ..." in content
