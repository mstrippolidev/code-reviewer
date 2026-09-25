import pytest

from code_reviewer.pipeline.pairing_stem import pairing_stem


@pytest.mark.parametrize(
    "file_path,expected_stem",
    [
        ("app/payment.py", "payment"),
        ("tests/test_payment.py", "payment"),
        ("app/payment_test.py", "payment"),
        ("app/Test_Payment.py", "payment"),
    ],
)
def test_pairing_stem_strips_test_naming_convention(file_path: str, expected_stem: str) -> None:
    """Verify a source file and each test naming convention normalize to the same stem."""
    assert pairing_stem(file_path) == expected_stem
