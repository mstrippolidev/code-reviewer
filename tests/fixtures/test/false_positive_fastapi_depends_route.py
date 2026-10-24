"""
    TEST false-positive fixture: a FastAPI route with real branching that
    receives its collaborator through Depends. A test replaces the
    provider with dependency_overrides, so the route is already isolatable
    and must NOT be flagged as logic trapped in a module-level function.
"""
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


class RepoStore:
    def find(self, repo_id: int) -> dict[str, str] | None:
        return None


def get_repo_store() -> RepoStore:
    return RepoStore()


@router.get("/repos/{repo_id}")
def read_repo(repo_id: int, user_id: str, store: RepoStore = Depends(get_repo_store)) -> dict[str, str]:
    repo = store.find(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repo not found")
    if repo["owner_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your repo")
    return repo
