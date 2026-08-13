"""
    ARCH false-positive fixture: a factory function whose entire declared
    purpose is building an object graph, with no unrelated business logic
    sharing the same place. Should NOT be flagged as construction mixed
    with use — a function named and scoped purely as a factory is exactly
    where assembly belongs; the caller uses the returned object elsewhere.
"""


class SmtpClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port


class HtmlRenderer:
    def __init__(self, template_name: str) -> None:
        self.template_name = template_name


class ReportMailer:
    def __init__(self, client: SmtpClient, renderer: HtmlRenderer) -> None:
        self._client = client
        self._renderer = renderer


def build_report_mailer(host: str, port: int, template_name: str) -> ReportMailer:
    client = SmtpClient(host, port)
    renderer = HtmlRenderer(template_name)
    return ReportMailer(client, renderer)
