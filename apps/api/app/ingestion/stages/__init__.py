"""Ingestion stage registry (S16).

Every stage starts as a **stub** (no-op) so a job reaches READY end to end; T3.5 replaces them
with the real validate / scan / parse / normalize / security-scan / chunk stages, and T4.2 with
embed / index / verify. A stage is `async (ctx, checkpoint) -> checkpoint` and must be idempotent:
it may run again after a crash before its checkpoint was stored.
"""

from collections.abc import Mapping

from app.domain.enums import IngestionState
from app.ingestion.runner import Checkpoint, StageContext, StageFn
from app.ingestion.state_machine import STAGES


async def _stub(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
    return {"stub": True}


STUB_STAGES: Mapping[IngestionState, StageFn] = dict.fromkeys(STAGES, _stub)


def default_stages() -> Mapping[IngestionState, StageFn]:
    """The stage implementations workers run. Stubs until T3.5 / T4.2 register real ones."""
    return STUB_STAGES
