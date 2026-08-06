from code_reviewer.pipeline.test_file_pairing import pair_source_files_with_tests
from code_reviewer.schemas.submission import SubmittedFile


def _file(path: str, content: str = "x") -> SubmittedFile:
    return SubmittedFile(file_path=path, content=content)


def _test_files_for(pairings, source_path: str) -> set[str]:
    pairing = next(p for p in pairings if p.source_file.file_path == source_path)
    return {test_file.file_path for test_file in pairing.test_files}


def test_prefix_convention_pairs_source_with_its_test_file() -> None:
    source_files = [_file("login.py")]
    test_files = [_file("test_login.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "login.py") == {"test_login.py"}


def test_suffix_convention_pairs_source_with_its_test_file() -> None:
    source_files = [_file("login.py")]
    test_files = [_file("login_test.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "login.py") == {"login_test.py"}


def test_matching_is_case_insensitive() -> None:
    source_files = [_file("login.py")]
    test_files = [_file("Test_Login.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "login.py") == {"Test_Login.py"}


def test_test_directory_file_without_naming_convention_still_pairs_by_basename() -> None:
    source_files = [_file("service.py")]
    test_files = [_file("tests/service.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "service.py") == {"tests/service.py"}


def test_source_with_no_matching_test_file_gets_empty_list() -> None:
    source_files = [_file("login.py")]
    test_files = [_file("test_billing.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "login.py") == set()


def test_submission_with_no_test_files_pairs_every_source_with_an_empty_list() -> None:
    source_files = [_file("login.py"), _file("billing.py")]

    pairings = pair_source_files_with_tests(source_files, [])

    assert _test_files_for(pairings, "login.py") == set()
    assert _test_files_for(pairings, "billing.py") == set()


def test_multiple_test_files_in_different_directories_all_pair_to_one_source() -> None:
    source_files = [_file("login.py")]
    test_files = [
        _file("tests/unit/test_login.py"),
        _file("tests/integration/test_login.py"),
    ]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "login.py") == {
        "tests/unit/test_login.py",
        "tests/integration/test_login.py",
    }


def test_ambiguous_stem_collision_pairs_neither_source() -> None:
    source_files = [
        _file("app/auth/utils.py"),
        _file("app/billing/utils.py"),
    ]
    test_files = [_file("test_utils.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "app/auth/utils.py") == set()
    assert _test_files_for(pairings, "app/billing/utils.py") == set()


def test_collision_on_one_stem_does_not_affect_unrelated_pairings() -> None:
    source_files = [
        _file("app/auth/utils.py"),
        _file("app/billing/utils.py"),
        _file("login.py"),
    ]
    test_files = [_file("test_utils.py"), _file("test_login.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    assert _test_files_for(pairings, "login.py") == {"test_login.py"}


def test_returns_exactly_one_pairing_per_source_file() -> None:
    source_files = [_file("login.py"), _file("billing.py")]
    test_files = [_file("test_login.py")]

    pairings = pair_source_files_with_tests(source_files, test_files)

    paired_source_paths = {p.source_file.file_path for p in pairings}
    assert paired_source_paths == {"login.py", "billing.py"}
