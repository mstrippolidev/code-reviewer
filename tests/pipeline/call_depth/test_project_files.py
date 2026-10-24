import pytest

from code_reviewer.pipeline.call_depth.project_files import ExternalCall, ProjectFiles, UnresolvedCall

SOURCES = {
    "app/service.py": "from app.pricing import PricingManager\n",
    "app/pricing.py": "class PricingManager:\n    pass\n",
    "app/tax/__init__.py": "def tax(amount):\n    return amount\n",
}


class FakeLoader:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files
        self.requested: list[str] = []

    def load(self, path: str) -> str:
        self.requested.append(path)
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]


def test_has_and_at_reflect_the_provided_files() -> None:
    files = ProjectFiles(SOURCES)

    assert files.has("app/service.py") is True
    assert files.has("app/missing.py") is False
    assert files.at("app/pricing.py").path == "app/pricing.py"


def test_module_name_resolves_to_a_file() -> None:
    assert ProjectFiles(SOURCES).module_named("app.pricing").path == "app/pricing.py"


def test_module_name_resolves_to_a_package_init() -> None:
    assert ProjectFiles(SOURCES).module_named("app.tax").path == "app/tax/__init__.py"


def test_project_module_without_a_file_is_unresolved() -> None:
    with pytest.raises(UnresolvedCall, match="app.missing"):
        ProjectFiles(SOURCES).module_named("app.missing")


def test_library_module_is_external() -> None:
    with pytest.raises(ExternalCall):
        ProjectFiles(SOURCES).module_named("json")


def test_file_outside_the_pr_is_fetched_from_the_loader() -> None:
    loader = FakeLoader({"app/rules.py": "def apply_rule(price):\n    return price\n"})
    files = ProjectFiles(SOURCES, loader)

    module = files.module_named("app.rules")

    assert module.path == "app/rules.py"
    assert (None, "apply_rule") in module.definitions


def test_loaded_file_is_parsed_once_and_reused() -> None:
    loader = FakeLoader({"app/rules.py": "def apply_rule(price):\n    return price\n"})
    files = ProjectFiles(SOURCES, loader)

    first = files.module_named("app.rules")
    second = files.module_named("app.rules")

    assert first is second
    assert loader.requested == ["app/rules.py"]


def test_pr_file_wins_over_the_loader() -> None:
    loader = FakeLoader({"app/pricing.py": "def stale():\n    pass\n"})
    files = ProjectFiles(SOURCES, loader)

    module = files.module_named("app.pricing")

    assert (None, "stale") not in module.definitions
    assert loader.requested == []


def test_loader_is_asked_for_the_package_init_when_the_module_file_is_missing() -> None:
    loader = FakeLoader({"app/rules/__init__.py": "def apply_rule(price):\n    return price\n"})
    files = ProjectFiles(SOURCES, loader)

    assert files.module_named("app.rules").path == "app/rules/__init__.py"
    assert loader.requested == ["app/rules.py", "app/rules/__init__.py"]


def test_module_missing_from_pr_and_loader_is_unresolved_when_it_is_project_code() -> None:
    files = ProjectFiles(SOURCES, FakeLoader({}))

    with pytest.raises(UnresolvedCall):
        files.module_named("app.missing")


def test_library_module_is_still_external_with_a_loader() -> None:
    files = ProjectFiles(SOURCES, FakeLoader({}))

    with pytest.raises(ExternalCall):
        files.module_named("json")


def test_file_that_does_not_parse_is_left_out_without_failing_the_others() -> None:
    files = ProjectFiles({**SOURCES, "app/broken.py": "def broken(:\n"})

    assert (files.has("app/broken.py"), files.has("app/pricing.py")) == (False, True)


def test_file_with_a_null_byte_is_left_out() -> None:
    files = ProjectFiles({**SOURCES, "app/binary.py": "x = 1\x00"})

    assert files.has("app/binary.py") is False


def test_import_of_a_file_that_does_not_parse_is_unresolved_not_external() -> None:
    files = ProjectFiles({**SOURCES, "app/broken.py": "def broken(:\n"})

    with pytest.raises(UnresolvedCall):
        files.module_named("app.broken")
