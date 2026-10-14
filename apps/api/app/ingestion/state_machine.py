"""Ingestion job state machine (plan §14, §14.1; S16).

States are `IngestionState`. Work stages run in a fixed order; every transition must appear in
`TRANSITIONS` (illegal moves raise), so a bug can never skip scanning or jump to READY.
"""

from app.domain.enums import TERMINAL_INGESTION_STATES, IngestionState

S = IngestionState

# Work stages in execution order. Each one is a checkpointed step of the runner.
STAGES: tuple[IngestionState, ...] = (
    S.VALIDATING,
    S.MALWARE_SCAN,
    S.PARSING,
    S.NORMALIZING,
    S.SECURITY_SCAN,
    S.CHUNKING,
    S.EMBEDDING,
    S.INDEXING,
    S.VERIFYING,
)

# Relative cost of each stage (parsing/OCR and embedding dominate), so progress moves at a
# believable pace. Progress shown when a stage *starts* is the share of the stages before it.
STAGE_WEIGHTS: dict[IngestionState, int] = {
    S.VALIDATING: 2,
    S.MALWARE_SCAN: 5,
    S.PARSING: 30,
    S.NORMALIZING: 3,
    S.SECURITY_SCAN: 5,
    S.CHUNKING: 10,
    S.EMBEDDING: 30,
    S.INDEXING: 10,
    S.VERIFYING: 5,
}
_TOTAL_WEIGHT = sum(STAGE_WEIGHTS.values())
PROGRESS: dict[IngestionState, int] = {
    stage: round(100 * sum(STAGE_WEIGHTS[s] for s in STAGES[:index]) / _TOTAL_WEIGHT)
    for index, stage in enumerate(STAGES)
}

_FAILURES = {S.FAILED_RETRYABLE, S.FAILED_PERMANENT, S.CANCELLED}


def _build() -> dict[IngestionState, frozenset[IngestionState]]:
    table: dict[IngestionState, set[IngestionState]] = {state: set() for state in IngestionState}
    table[S.RECEIVED] = {STAGES[0], *_FAILURES}
    for current, following in zip(STAGES, (*STAGES[1:], S.READY), strict=True):
        table[current] = {following, *_FAILURES}
    table[S.MALWARE_SCAN].add(S.QUARANTINED)  # infected file
    table[S.SECURITY_SCAN] |= {S.QUARANTINED, S.PENDING_APPROVAL}  # content-scan policy outcome
    table[S.PENDING_APPROVAL] = {S.CHUNKING, S.QUARANTINED, S.CANCELLED}  # approve / reject
    # A retryable failure resumes at any stage (the runner continues after the last checkpoint),
    # or re-parks if its SECURITY_SCAN checkpoint holds for approval that was never given.
    table[S.FAILED_RETRYABLE] = {*STAGES, S.PENDING_APPROVAL, S.FAILED_PERMANENT, S.CANCELLED}
    for terminal in TERMINAL_INGESTION_STATES:
        table[terminal] = set()
    return {state: frozenset(targets) for state, targets in table.items()}


TRANSITIONS: dict[IngestionState, frozenset[IngestionState]] = _build()


class InvalidTransition(ValueError):
    def __init__(self, current: IngestionState, target: IngestionState) -> None:
        super().__init__(f"illegal ingestion transition {current.value} -> {target.value}")
        self.current, self.target = current, target


def ensure_transition(current: IngestionState, target: IngestionState) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(current, target)


def is_terminal(state: IngestionState) -> bool:
    return state in TERMINAL_INGESTION_STATES
