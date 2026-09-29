"""
    Shared line-numbering instruction for every chunk agent (VAR, ERR, CMT,
    CONC, CMPLX, TEST) — dispatch hands each of them code with a line
    number prefixed to every line, so line_position comes from reading
    that number rather than the model counting or estimating it.
"""

CHUNK_LINE_NUMBERING_INSTRUCTION = """Every line of the code you are given is
  prefixed with its line number and a colon, e.g. "3: def foo():" —
  numbering starts at 1 for the first line shown to you. Read a finding's
  line_position directly off these prefixes; never count lines yourself or
  estimate a position. The "N:" prefix is not part of the code itself —
  never quote it in description or advice."""
