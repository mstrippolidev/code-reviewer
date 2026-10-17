"""
    SOLID2 false-positive trap: a FastAPI route that receives its
    collaborator through a Depends provider. A test replaces it with
    `dependency_overrides`, so it is already substitutable and needs no
    extra Protocol.
"""
from fastapi import APIRouter, Depends

router = APIRouter()


class RepoLister:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def names_for(self, owner_id: int) -> list[str]:
        return [f"{self._database_url}/{owner_id}"]


def get_repo_lister() -> RepoLister:
    return RepoLister("postgresql://localhost/code_reviewer")


@router.get("/repos/{owner_id}")
def list_repo_names(owner_id: int, lister: RepoLister = Depends(get_repo_lister)) -> list[str]:
    return lister.names_for(owner_id)
