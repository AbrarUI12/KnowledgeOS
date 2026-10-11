"""Versioned API router. Only Claude registers routers here (docs/AGENT_WORKFLOW.md §4)."""

from fastapi import APIRouter

from app.api.v1 import identity, knowledge, retrieval

api_v1_router = APIRouter(prefix="/v1")
api_v1_router.include_router(identity.router)
api_v1_router.include_router(knowledge.router)
api_v1_router.include_router(retrieval.router)
