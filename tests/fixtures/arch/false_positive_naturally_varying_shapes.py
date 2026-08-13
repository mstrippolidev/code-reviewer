"""
    ARCH false-positive fixture: repository methods with different
    return shapes because the operations themselves are genuinely
    different, not because the file lacks a convention. Should NOT be
    flagged as pattern inconsistency — a single lookup, a bulk query, and
    a count each have a return shape their operation demands, and every
    method here goes through the same domain object where one is
    returned at all.
"""
import sqlite3
from dataclasses import dataclass


@dataclass
class Customer:
    customer_id: str
    email: str


class CustomerRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def by_id(self, customer_id: str) -> Customer:
        row = self._connection.execute(
            "SELECT id, email FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        return Customer(row[0], row[1])

    def all_active(self) -> list[Customer]:
        rows = self._connection.execute(
            "SELECT id, email FROM customers WHERE status = 'active'"
        ).fetchall()
        return [Customer(row[0], row[1]) for row in rows]

    def count_active(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM customers WHERE status = 'active'"
        ).fetchone()
        return row[0]
