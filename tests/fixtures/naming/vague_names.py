"""
    Naming fixture: vague, generic names that reveal nothing about intent.
"""


def process(data: list) -> list:
    result = []
    for item in data:
        if item.get("flag"):
            result.append(item)
    return result


class Manager:
    def __init__(self, obj: dict) -> None:
        self.obj = obj

    def handle(self) -> None:
        pass
