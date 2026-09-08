"""
    SOLID1 out-of-scope fixture, deliberately distinct from the worked
    example now in the prompt (temporal coupling / unenforced call
    order): a class carrying an unused extension point built for a
    strategy that does not exist yet. This is OCP-adjacent — it's about
    extension, just the opposite failure direction from item 2's
    if/elif-chain (that's rigidity; this is speculative complexity paid
    for before any second case is real) — but it is not itself an
    unrelated-responsibilities bundle, an if/elif-chain OCP violation, a
    multi-thing function, a param-count issue, or a boolean flag
    argument, so it must land outside the five in-scope categories.
"""


class InvoicePdfExporter:
    def __init__(self, strategy_name: str = "default") -> None:
        self._strategy_name = strategy_name

    def _pre_export_hook(self) -> None:
        pass

    def _post_export_hook(self) -> None:
        pass

    def export(self, rows: list[str]) -> str:
        self._pre_export_hook()
        body = "\n".join(rows)
        self._post_export_hook()
        return body
