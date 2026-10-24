from fastapi import Header, HTTPException

from app.repository import Repository


def current_user(authorization: str = Header(...)) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return int(authorization.removeprefix("Bearer "))


def get_repository() -> Repository:
    return Repository()
