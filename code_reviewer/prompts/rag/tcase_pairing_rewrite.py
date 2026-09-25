"""
    System prompt for the TCASE pairing query rewrite: after a first search
    found no confirmed test file, produces a different query for one retry.
"""

TCASE_PAIRING_REWRITE_SYSTEM_PROMPT = """
A search for the test file of one source file came back without a single
confirmed match. You will be given the SOURCE FILE and, when the search
found anything at all, the reasons each rejected candidate was not its
test file. Write a new search query for one more attempt.

The query is embedded and compared against short behavioral summaries of
every file in the repository, including its test files. So describe the
test file you are looking for the way its own summary would read: which
classes and functions it calls and what behavior it asserts, using the
source file's real symbol names.

Use the rejection reasons to steer away from what already failed. If the
rejected candidates tested a similarly named but different module, name
this source's module and symbols more precisely. If there are no
rejection reasons because nothing was found, describe the test file more
broadly — its likely scenarios and the public entry points it would
exercise — rather than repeating the source file's own summary.

Write two or three plain sentences. Do not include code, file paths you
are guessing at, or commentary about the search itself.
"""
