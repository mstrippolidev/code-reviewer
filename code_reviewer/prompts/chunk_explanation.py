"""
    System prompt for generating a code chunk's short explanation, used to
    strengthen DRY's semantic duplicate search.
"""

CHUNK_EXPLANATION_SYSTEM_PROMPT = """You are given one function or class. Describe in one or \
two short sentences what it does — the behavior and purpose, not the syntax or control flow. Two \
functions that accomplish the same thing in different ways must get the same kind of \
description; ignore variable names, framework, and implementation style. Do not mention line \
numbers, do not restate the code, do not add caveats."""
