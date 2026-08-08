"""
    OCP violation fixture: adding a new shape means editing
    calculate_area's if/elif chain, instead of extending the code with a
    new type that plugs in without modifying existing branches.
"""


def calculate_area(shape_kind: str, dimensions: dict) -> float:
    if shape_kind == "circle":
        return 3.14159 * dimensions["radius"] ** 2
    elif shape_kind == "rectangle":
        return dimensions["width"] * dimensions["height"]
    elif shape_kind == "triangle":
        return 0.5 * dimensions["base"] * dimensions["height"]
    else:
        raise ValueError(f"Unknown shape kind: {shape_kind}")
