"""
    Judge-panel prompts for confirming a critical finding, one per agent.
"""
from code_reviewer.prompts.agents.architecture import ARCH_CRITICAL_CRITERION
from code_reviewer.prompts.agents.boundaries import BOUND_CRITICAL_CRITERION
from code_reviewer.prompts.agents.cohesion import COH_CRITICAL_CRITERION
from code_reviewer.prompts.agents.comments import COMMENTS_CRITICAL_CRITERION
from code_reviewer.prompts.agents.complexity import CMPLX_CRITICAL_CRITERION
from code_reviewer.prompts.agents.concurrency import CONC_CRITICAL_CRITERION
from code_reviewer.prompts.agents.coupling import COUP_CRITICAL_CRITERION
from code_reviewer.prompts.agents.coverage_gap import TCASE_CRITICAL_CRITERION
from code_reviewer.prompts.agents.errors import ERR_CRITICAL_CRITERION
from code_reviewer.prompts.agents.naming import VAR_CRITICAL_CRITERION
from code_reviewer.prompts.agents.solid_1 import SOLID1_CRITICAL_CRITERION
from code_reviewer.prompts.agents.solid_2 import SOLID2_CRITICAL_CRITERION
from code_reviewer.prompts.agents.testability import TEST_CRITICAL_CRITERION
from code_reviewer.schemas.review import CodeKey

_CONFIRMATION_TEMPLATE = """
You are confirming whether a single code-review finding really meets one
specific severity bar. You are not reviewing the code and must not look for
any other problem in it.

A reviewer flagged the finding below as `critical`. For this review,
`critical` means exactly:

{criterion}

Answer true only if the finding meets that bar as written. Answer false if
the finding is a real problem but does not reach that bar — a genuine issue
at a lower severity is the common case, and false is the correct answer for
it. Answer false as well if the code does not actually contain what the
finding describes.

Judge only the finding you are given, against only the definition above.
"""


def _confirmation_prompt(criterion: str) -> str:
    return _CONFIRMATION_TEMPLATE.format(criterion=" ".join(criterion.split()))


CRITICAL_CONFIRMATION_PROMPTS: dict[CodeKey, str] = {
    CodeKey.SOLID1: _confirmation_prompt(SOLID1_CRITICAL_CRITERION),
    CodeKey.SOLID2: _confirmation_prompt(SOLID2_CRITICAL_CRITERION),
    CodeKey.COH: _confirmation_prompt(COH_CRITICAL_CRITERION),
    CodeKey.COUP: _confirmation_prompt(COUP_CRITICAL_CRITERION),
    CodeKey.TEST: _confirmation_prompt(TEST_CRITICAL_CRITERION),
    CodeKey.TCASE: _confirmation_prompt(TCASE_CRITICAL_CRITERION),
    CodeKey.CONC: _confirmation_prompt(CONC_CRITICAL_CRITERION),
    CodeKey.CMPLX: _confirmation_prompt(CMPLX_CRITICAL_CRITERION),
    CodeKey.ARCH: _confirmation_prompt(ARCH_CRITICAL_CRITERION),
    CodeKey.BOUND: _confirmation_prompt(BOUND_CRITICAL_CRITERION),
    CodeKey.VAR: _confirmation_prompt(VAR_CRITICAL_CRITERION),
    CodeKey.ERR: _confirmation_prompt(ERR_CRITICAL_CRITERION),
    CodeKey.CMT: _confirmation_prompt(COMMENTS_CRITICAL_CRITERION),
}
