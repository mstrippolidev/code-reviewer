"""
    ARCH construction-mixed-with-use fixture: ReportMailer assembles its
    own object graph in the middle of the logic that uses it — reading
    configuration, building a client, building a renderer — so one place
    both decides what the system is made of and does the work.
"""
import os


class SmtpClient:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def send(self, recipient: str, body: str) -> None:
        print(f"{self._host}:{self._port} -> {recipient}: {body}")


class HtmlRenderer:
    def __init__(self, template_name: str) -> None:
        self._template_name = template_name

    def render(self, rows: list[str]) -> str:
        return f"<{self._template_name}>" + "".join(rows) + f"</{self._template_name}>"


class ReportMailer:
    def mail_daily_report(self, recipient: str, rows: list[str]) -> None:
        host = os.environ.get("SMTP_HOST", "localhost")
        port = int(os.environ.get("SMTP_PORT", "25"))
        client = SmtpClient(host, port)
        renderer = HtmlRenderer(os.environ.get("REPORT_TEMPLATE", "table"))
        body = renderer.render(rows)
        client.send(recipient, body)
