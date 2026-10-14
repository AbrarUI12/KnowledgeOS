"""Ingestion state machine, backoff and worker configuration (T3.1, S16): pure tests."""

import random
from itertools import pairwise

import pytest

from app.domain.enums import TERMINAL_INGESTION_STATES, IngestionState
from app.ingestion.errors import backoff_seconds
from app.ingestion.state_machine import (
    PROGRESS,
    STAGES,
    TRANSITIONS,
    InvalidTransition,
    ensure_transition,
)

pytestmark = pytest.mark.unit
S = IngestionState


def test_happy_path_walks_every_stage_in_order() -> None:
    path = [S.RECEIVED, *STAGES, S.READY]
    for current, target in pairwise(path):
        ensure_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.RECEIVED, S.READY),  # can't skip the pipeline
        (S.VALIDATING, S.PARSING),  # can't skip malware scanning
        (S.PARSING, S.CHUNKING),  # can't skip the content-security scan
        (S.READY, S.PARSING),  # terminal states are final
        (S.QUARANTINED, S.CHUNKING),
        (S.FAILED_PERMANENT, S.VALIDATING),
        (S.CANCELLED, S.RECEIVED),
    ],
)
def test_illegal_transitions_raise(current: IngestionState, target: IngestionState) -> None:
    with pytest.raises(InvalidTransition):
        ensure_transition(current, target)


def test_terminal_states_have_no_exits_and_every_stage_can_fail() -> None:
    for state in TERMINAL_INGESTION_STATES:
        assert TRANSITIONS[state] == frozenset()
    for stage in (S.RECEIVED, *STAGES):
        assert {S.FAILED_RETRYABLE, S.FAILED_PERMANENT, S.CANCELLED} <= TRANSITIONS[stage]


def test_retryable_failures_resume_at_any_stage() -> None:
    for stage in STAGES:
        ensure_transition(S.FAILED_RETRYABLE, stage)


def test_quarantine_and_approval_come_only_from_scans() -> None:
    sources = {s for s, targets in TRANSITIONS.items() if S.QUARANTINED in targets}
    assert sources == {S.MALWARE_SCAN, S.SECURITY_SCAN, S.PENDING_APPROVAL}
    assert {s for s, t in TRANSITIONS.items() if S.PENDING_APPROVAL in t} == {S.SECURITY_SCAN}


def test_progress_increases_with_each_stage() -> None:
    values = [PROGRESS[s] for s in STAGES]
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] < 100


def test_backoff_is_jittered_exponential_and_capped() -> None:
    rng = random.Random(42)  # noqa: S311 (deterministic test sampling)
    for attempt in range(1, 12):
        ceiling = min(900.0, 10.0 * 2 ** (attempt - 1))
        samples = [backoff_seconds(attempt, rng=rng) for _ in range(200)]
        assert all(0 <= s <= ceiling for s in samples)
        assert max(samples) > ceiling / 2  # full jitter actually spreads
    with pytest.raises(ValueError, match="1-based"):
        backoff_seconds(0)


def test_celery_reliability_settings() -> None:
    from app.workers.celery_app import QUEUES, celery_app

    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_serializer == "json"
    assert list(conf.accept_content) == ["json"]
    assert conf.task_time_limit > conf.task_soft_time_limit
    assert set(QUEUES) == {"ingestion", "sync", "maintenance", "eval", "llm"}
    assert {"ingestion.process_job", "acl.sync_knowledge_base"} <= set(celery_app.tasks)
