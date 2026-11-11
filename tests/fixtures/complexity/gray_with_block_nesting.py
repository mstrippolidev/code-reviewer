"""
    CMPLX gray-area fixture: a with block around a loop around a condition. The
    prompt counts if/else, loops and try/except as nesting levels and does not
    list with blocks, so the depth is two or three depending on the reading.
"""


def count_error_lines(path: str) -> int:
    count = 0
    with open(path) as handle:
        for line in handle:
            if "ERROR" in line:
                count += 1
    return count
