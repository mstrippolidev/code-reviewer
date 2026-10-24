class Repository:
    def list_for(self, user_id: int) -> list[dict]:
        if user_id <= 0:
            return []
        return [{"id": 1, "owner": user_id}]
