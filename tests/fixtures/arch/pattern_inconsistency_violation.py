"""
    ARCH pattern-inconsistency fixture: three sibling lookups on the same
    repository, each with a visibly different shape. One returns a domain
    object, one returns a raw driver row, one returns a plain dict, so
    the file establishes no convention a caller can rely on.
"""
import sqlite3


class Customer:
    def __init__(self, customer_id: str, email: str) -> None:
        self.customer_id = customer_id
        self.email = email


class CustomerRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def by_id(self, customer_id: str) -> Customer:
        row = self._connection.execute(
            "SELECT id, email FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        return Customer(row[0], row[1])

    def by_email(self, email: str) -> tuple:
        return self._connection.execute(
            "SELECT id, email FROM customers WHERE email = ?", (email,)
        ).fetchone()

    def by_status(self, status: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT id, email FROM customers WHERE status = ?", (status,)
        ).fetchall()
        return [{"id": row[0], "email": row[1]} for row in rows]
