"""
    CMT out-of-scope fixture: an accurate but unprofessional comment. It
    isn't redundant, isn't stale, isn't commented-out code, and isn't a
    docstring leaking implementation reasoning — it's a tone/professionalism
    problem, comment-adjacent but outside the four in-scope categories, so
    it must still be flagged, but only at priority low.
"""


def calculate_shipping_cost(weight_kg: float) -> float:
    # ugh this pricing formula is such a mess but whatever, not my problem
    return weight_kg * 4.5 + 2.0
