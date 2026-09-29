"""Investigation workflow steps and statuses."""

from enum import StrEnum


class Step(StrEnum):
    STARTED = "STARTED"
    TRANSACTION_DATA_COLLECTED = "TRANSACTION_DATA_COLLECTED"
    RELATED_EVENTS_COLLECTED = "RELATED_EVENTS_COLLECTED"
    KNOWLEDGE_RETRIEVED = "KNOWLEDGE_RETRIEVED"
    AI_ANALYSIS_COMPLETED = "AI_ANALYSIS_COMPLETED"
    RESULT_VERIFIED = "RESULT_VERIFIED"
    COMPLETED = "COMPLETED"


STEPS: tuple[Step, ...] = tuple(Step)  # execution order


class Status(StrEnum):
    OPEN = "OPEN"  # queued, never claimed
    IN_PROGRESS = "IN_PROGRESS"  # claimed; reclaimable once its lease expires
    AWAITING_REVIEW = "AWAITING_REVIEW"  # report ready for a human
    FAILED = "FAILED"  # attempts exhausted
    AUTO_RESOLVED = "AUTO_RESOLVED"  # finding resolved before a human decided


def remaining(completed: set[str]) -> list[Step]:
    """Steps still to run, in order. Completed steps are never re-run."""
    return [step for step in STEPS if step not in completed]
