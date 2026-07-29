"""
    Comment fixture: comments that just restate what the code already says.
"""


def increment_counter(counter: int) -> int:
    # Increment the counter by one
    return counter + 1


class UserRepository:
    def __init__(self, database: object) -> None:
        # Set the database
        self.database = database
