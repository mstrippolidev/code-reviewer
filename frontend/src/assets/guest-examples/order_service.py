import smtplib
import sqlite3
from datetime import datetime


class OrderService:
    def __init__(self):
        self.db = sqlite3.connect("orders.db")
        self.smtp = smtplib.SMTP("smtp.example.com", 587)
        self.tax_rate = 0.21

    def place_order(self, customer_email, items, coupon_code, is_express, send_receipt):
        subtotal = 0
        for item in items:
            subtotal += item["price"] * item["quantity"]

        if coupon_code == "SUMMER10":
            subtotal = subtotal * 0.9
        elif coupon_code == "VIP20":
            subtotal = subtotal * 0.8

        total = subtotal + subtotal * self.tax_rate
        if is_express:
            total += 15

        cursor = self.db.cursor()
        cursor.execute(
            "INSERT INTO orders (email, total, created_at) VALUES (?, ?, ?)",
            (customer_email, total, datetime.now().isoformat()),
        )
        self.db.commit()

        if send_receipt:
            message = f"Subject: Your receipt\n\nThanks! Your total is ${total:.2f}"
            self.smtp.sendmail("shop@example.com", customer_email, message)

        return cursor.lastrowid

    def monthly_report(self):
        cursor = self.db.cursor()
        rows = cursor.execute("SELECT total FROM orders").fetchall()
        report = "Monthly revenue report\n"
        report += "=" * 24 + "\n"
        report += f"Orders: {len(rows)}\n"
        report += f"Revenue: ${sum(row[0] for row in rows):.2f}\n"
        return report

    def refund(self, order_id):
        cursor = self.db.cursor()
        cursor.execute("UPDATE orders SET total = 0 WHERE id = ?", (order_id,))
        self.db.commit()
