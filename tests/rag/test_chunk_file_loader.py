import ast

import pytest

from code_reviewer.pipeline.call_depth.depth_follower import CallDepthFollower, WalkEnd
from code_reviewer.pipeline.call_depth.project_files import ProjectFiles
from code_reviewer.pipeline.call_depth.thin_body import ThinBodyClassifier
from code_reviewer.rag.chunk_file_loader import ChunkFileLoader
from code_reviewer.rag.indexer import FileChunk
from code_reviewer.rag.repo_data import RepoData

REPO_DATA = RepoData(repo_id="42", commit_sha="abc123", owner_id="owner-1")


def chunk(path: str, name: str, start_line: int, code: str, imports: list[str] | None = None) -> FileChunk:
    return FileChunk(
        file_path=path,
        chunk_name=name,
        start_line=start_line,
        end_line=start_line + code.count("\n"),
        text="explanation",
        code=code,
        imports=imports or [],
    )


class StubRagManager:
    def __init__(self, chunks_by_path: dict[str, list[FileChunk]]) -> None:
        self._chunks_by_path = chunks_by_path
        self.requests: list[tuple[str, str | None, str]] = []

    def get_file_chunks(self, repo_id: str, owner_id: str | None, file_path: str) -> list[FileChunk]:
        self.requests.append((repo_id, owner_id, file_path))
        return self._chunks_by_path.get(file_path, [])


def loader_for(chunks_by_path: dict[str, list[FileChunk]]) -> ChunkFileLoader:
    return ChunkFileLoader(StubRagManager(chunks_by_path), REPO_DATA)


def test_source_is_the_imports_followed_by_every_chunk_in_file_order() -> None:
    imports = ["from app.rules import apply_rule"]
    chunks = [
        chunk("app/pricing.py", "second", 9, "def second(x):\n    return x", imports),
        chunk("app/pricing.py", "PricingManager", 3, "class PricingManager:\n    pass", imports),
    ]

    source = loader_for({"app/pricing.py": chunks}).load("app/pricing.py")

    assert source == (
        "from app.rules import apply_rule\n\n"
        "class PricingManager:\n    pass\n\n"
        "def second(x):\n    return x"
    )


def test_imports_shared_by_every_chunk_are_written_once_in_first_seen_order() -> None:
    chunks = [
        chunk("a.py", "one", 5, "def one():\n    pass", ["import os", "from app import x"]),
        chunk("a.py", "two", 9, "def two():\n    pass", ["import os", "from app import x"]),
    ]

    source = loader_for({"a.py": chunks}).load("a.py")

    assert source.splitlines()[:3] == ["import os", "", "from app import x"]
    assert source.count("import os") == 1


def test_chunks_indexed_before_imports_were_stored_still_load() -> None:
    chunks = [chunk("a.py", "one", 1, "def one():\n    return 1")]

    assert loader_for({"a.py": chunks}).load("a.py") == "def one():\n    return 1"


def test_rebuilt_source_is_valid_python() -> None:
    imports = ["from app.rules import (\n    apply_rule,\n    other_rule,\n)"]
    chunks = [chunk("a.py", "one", 7, "def one():\n    return apply_rule(1)", imports)]

    source = loader_for({"a.py": chunks}).load("a.py")

    ast.parse(source)


def test_lookup_is_scoped_to_the_repo_and_owner() -> None:
    manager = StubRagManager({"a.py": [chunk("a.py", "one", 1, "def one():\n    pass")]})

    ChunkFileLoader(manager, REPO_DATA).load("a.py")

    assert manager.requests == [("42", "owner-1", "a.py")]


def test_path_without_chunks_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError, match="missing.py"):
        loader_for({}).load("missing.py")


def test_chunks_without_stored_code_raise_file_not_found() -> None:
    chunks = [chunk("a.py", "one", 1, "")]

    with pytest.raises(FileNotFoundError):
        loader_for({"a.py": chunks}).load("a.py")


def test_follower_crosses_files_that_only_exist_as_chunks() -> None:
    imports_in_service = ["from app.pricing import PricingManager"]
    chunks_by_path = {
        "app/pricing.py": [
            chunk(
                "app/pricing.py",
                "PricingManager",
                3,
                "class PricingManager:\n    def price_for(self, price):\n        return apply_rule(price)",
                ["from app.rules import apply_rule"],
            )
        ],
        "app/rules.py": [
            chunk("app/rules.py", "apply_rule", 1, "def apply_rule(price):\n    if price > 100:\n        return price * 0.9\n    return price")
        ],
    }
    service = (
        f"{imports_in_service[0]}\n\n"
        "class Checkout:\n"
        "    def __init__(self, manager: PricingManager) -> None:\n"
        "        self._manager = manager\n\n"
        "    def total(self, price):\n"
        "        return self._manager.price_for(price)\n"
    )
    files = ProjectFiles({"app/service.py": service}, loader_for(chunks_by_path))

    report = CallDepthFollower(files, ThinBodyClassifier()).report_for("app/service.py", "Checkout.total")

    call = report.calls[0]
    assert call.other_files == ["app/pricing.py", "app/rules.py"]
    assert call.ended_at is WalkEnd.REAL_LOGIC
