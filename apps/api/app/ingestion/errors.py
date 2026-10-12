"""Stage failure classes and retry backoff (S16, plan §34.2)."""

import random


class StageError(Exception):
    """Base for expected stage failures. `code` is stable; `safe_detail` may be shown to users."""

    code = "stage_failed"

    def __init__(self, safe_detail: str, *, code: str | None = None) -> None:
        super().__init__(safe_detail)
        self.safe_detail = safe_detail
        if code:
            self.code = code


class RetryableError(StageError):
    """Transient: timeouts, network errors, 5xx/429 from a dependency. Retried with backoff."""

    code = "transient_failure"


class PermanentError(StageError):
    """Won't succeed on retry: validation rejection, unsupported or corrupt content."""

    code = "permanent_failure"


def backoff_seconds(
    attempt: int,
    *,
    base: float = 10.0,
    cap: float = 900.0,
    rng: random.Random | None = None,
) -> float:
    """Exponential backoff with full jitter: uniform(0, min(cap, base * 2**(attempt-1))).

    `attempt` is 1-based (the number of failures so far). Full jitter spreads retries of many
    jobs that failed together (e.g. during a model-provider outage).
    """
    if attempt < 1:
        raise ValueError("attempt is 1-based")
    ceiling = min(cap, base * 2 ** (attempt - 1))
    return (rng or random).uniform(0, ceiling)
