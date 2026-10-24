import httpx


def fetch_profile(user_id: int) -> dict:
    response = _get(f"https://api.example.com/users/{user_id}")
    if response.status_code == 404:
        raise LookupError(f"User {user_id} does not exist")
    return response.json()


def _get(url: str) -> httpx.Response:
    return httpx.get(url)
