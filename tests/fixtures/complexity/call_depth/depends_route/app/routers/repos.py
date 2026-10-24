from fastapi import APIRouter, Depends

from app.dependencies import current_user, get_repository
from app.repository import Repository

router = APIRouter()


@router.get("/repos")
def list_repos(
    user_id: int = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> list[dict]:
    return repository.list_for(user_id)
