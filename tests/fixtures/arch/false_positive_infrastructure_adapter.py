"""
    ARCH false-positive fixture: an adapter class whose entire declared
    job is talking to a database. Should NOT be flagged — a class named
    and scoped as a repository is exactly where SQL and connections
    belong; the violation would be a business rule reaching for this
    directly, not this class existing.
"""
import sqlite3


class SqliteOrderRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, order_id: str, total: float) -> None:
        self._connection.execute(
            "INSERT INTO orders (id, total) VALUES (?, ?)", (order_id, total)
        )
        self._connection.commit()

    def total_for(self, order_id: str) -> float:
        row = self._connection.execute(
            "SELECT total FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return row[0]
