"""
    TEST priority=high fixture: a hard-coded dependency on an internal but
    non-trivial collaborator. ReportGenerator builds its own
    TemplateRenderer inside generate(), so a test cannot substitute a
    fake renderer without patching internals.
"""


class TemplateRenderer:
    def render(self, template_name: str, context: dict) -> str:
        return f"<rendered {template_name} with {context}>"


class ReportGenerator:
    def generate(self, report_name: str, data: dict) -> str:
        renderer = TemplateRenderer()
        return renderer.render(report_name, data)
