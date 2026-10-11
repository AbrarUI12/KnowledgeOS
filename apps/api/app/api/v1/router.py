"""Versioned API router. Feature routers are included here as sessions add them."""

from fastapi import APIRouter

api_v1_router = APIRouter(prefix="/v1")
