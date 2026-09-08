"""
    TEST false-positive fixture: a staticmethod doing one trivial,
    branch-free calculation. Should NOT be flagged by item 3 — that rule
    targets non-trivial branching logic trapped with no seam; a one-line
    pure formula needs no injection point to be exercised in isolation.
"""


class Circle:
    @staticmethod
    def area(radius: float) -> float:
        return 3.14159 * radius * radius
