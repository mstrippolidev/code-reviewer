"""
    The question a judge panel answers before reviewed code is allowed into
    the exemplar corpus.
"""
from code_reviewer.rag.errors import UnsupportedExemplarPrincipleError
from code_reviewer.schemas.review import CodeKey

PRINCIPLE_STATEMENTS: dict[CodeKey, str] = {
    CodeKey.SOLID1: (
        "the Single Responsibility and Open/Closed principles — one reason to "
        "change per unit, and behaviour extended without editing what already works"
    ),
    CodeKey.SOLID2: (
        "the Liskov Substitution, Interface Segregation and Dependency Inversion "
        "principles — subtypes honouring their parent's contract, clients depending "
        "on no more of an interface than they use, and dependencies pointing at "
        "abstractions rather than concretions"
    ),
}

_PROMPTS_TEMPLATE = """You are judging whether one fragment of code belongs in a small, permanent
corpus of teaching examples for {principle}.

The fragment reaching you already scored 100 in an automated review. That
means only that no problem was found in it. It is not evidence that the
fragment teaches anything — a one-line getter scores 100. Your question is
different: would a reviewer reading this fragment alongside unfamiliar code
learn something about how this principle is applied well?

Answer True only if ALL of the following hold:

1. It DEMONSTRATES the principle. The principle is visible in how the code is
   structured, not merely left un-violated by code too small to violate it.
2. It is SUBSTANTIAL enough for the principle to show. A fragment containing
   no design decision teaches nothing, however correct it is.
3. It READS ALONE. Someone without the rest of the file can follow what it
   does and why it is shaped this way.
4. It is NOT a counter-example in disguise. It must not break other design
   principles in ways that would teach a bad habit alongside the good one.

Answer False if any of these fail, and answer False when you are unsure.

A weak exemplar is worse than no exemplar. Anything promoted here is
retrieved into future reviews and silently shapes how other people's code is
judged, so the cost of admitting a mediocre example is paid repeatedly while
the cost of rejecting a borderline one is paid once and is close to zero.

Give your reasoning in one sentence, then your verdict."""


def build_promotion_prompt(code_key: CodeKey) -> str:
    """Build the judge question for one principle.

    Raises:
        UnsupportedExemplarPrincipleError: If no exemplar corpus is retrieved
            for this principle, so promoting into it would store a row that
            nothing can ever read.
    """
    statement = PRINCIPLE_STATEMENTS.get(code_key)
    if statement is None:
        raise UnsupportedExemplarPrincipleError(
            f"{code_key.value} has no exemplar promotion criteria; "
            f"supported: {sorted(key.value for key in PRINCIPLE_STATEMENTS)}."
        )
    return _PROMPTS_TEMPLATE.format(principle=statement)
