def count_matches(values: list[int], target: int) -> int:
    matches = 0
    for value in values:
        if value == target:
            matches += 1
    return matches
