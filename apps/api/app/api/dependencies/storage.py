"""Object-store dependency (tests override it with InMemoryObjectStore)."""

from typing import Annotated

from fastapi import Depends, Request

from app.providers.storage import ObjectStore


def get_object_store(request: Request) -> ObjectStore:
    store: ObjectStore = request.app.state.object_store
    return store


Storage = Annotated[ObjectStore, Depends(get_object_store)]
