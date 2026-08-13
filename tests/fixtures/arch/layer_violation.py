"""
    ARCH layer-violation fixture: a domain entity reaching straight for
    infrastructure. Subscription is a business concept, but it opens its
    own database connection, issues SQL, and reads an environment
    variable, so the renewal rule cannot be run or reasoned about without
    a live database present.
"""
import os
import sqlite3
from datetime import date


class Subscription:
    def __init__(self, subscriber_id: str, renews_on: date) -> None:
        self.subscriber_id = subscriber_id
        self.renews_on = renews_on

    def is_due(self, today: date) -> bool:
        return self.renews_on <= today

    def renew(self, today: date) -> None:
        if not self.is_due(today):
            return
        connection = sqlite3.connect(os.environ["BILLING_DB_PATH"])
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE subscriptions SET renews_on = ? WHERE subscriber_id = ?",
            (today.isoformat(), self.subscriber_id),
        )
        connection.commit()
        connection.close()
