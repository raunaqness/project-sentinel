"""Deliberate crashes for demonstrating recovery (spec §21).

`FAIL_AFTER_STEP=<Step>` kills the process right after that step's checkpoint commits.
`FAIL_AFTER_STEP=LLM_RESPONSE` kills it after the LLM answered but *before* the
analysis checkpoint commits — the spec's mandatory crash scenario (§9).
Faults apply only to an investigation's first attempt, so a restarted worker recovers.
"""

import logging
import os

from sentinel.workflow.states import Step

log = logging.getLogger("sentinel.failure_injection")

LLM_RESPONSE = "LLM_RESPONSE"
VALID_POINTS = frozenset({*Step, LLM_RESPONSE})


def crash_if(point: str, fault: str | None) -> None:
    if fault == point:
        log.warning("injected crash", extra={"fail_after_step": point})
        logging.shutdown()
        os._exit(1)  # hard kill: no cleanup, no lease release, no commit
