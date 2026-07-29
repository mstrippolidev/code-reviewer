"""
    Naming fixture: unexplained abbreviations that should be flagged by VAR.
"""


def calc_ttl(itms: list[float]) -> float:
    ttl = 0.0
    for itm in itms:
        ttl += itm
    return ttl


class UsrMgr:
    """Manages user records."""

    def __init__(self, db_cfg: dict) -> None:
        self.db_cfg = db_cfg

    def upd_usr(self, uid: int, nm: str) -> None:
        pass
