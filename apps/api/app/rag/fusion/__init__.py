"""Hybrid retrieval fusion (T4.3): weighted Reciprocal Rank Fusion + diversity caps.

Pure, deterministic, DB-free. Consumes the per-branch `RankedHit`s from the search backend and
produces the fused, de-duplicated list the reranker (T5.1) consumes.
"""

from app.rag.fusion.rrf import FusionConfig, reciprocal_rank_fusion

__all__ = ["FusionConfig", "reciprocal_rank_fusion"]
