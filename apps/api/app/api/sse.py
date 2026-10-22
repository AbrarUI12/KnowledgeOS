"""Server-Sent Events framing (docs/api/sse-events.md): `event:` + one-line JSON `data:` + blank
line; `("comment", None)` becomes a `: keep-alive` comment."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing

from pydantic import BaseModel


def frame(event: str, payload: BaseModel | None) -> bytes:
    if payload is None:
        return b": keep-alive\n\n"
    # model_dump_json never emits raw newlines (they're escaped inside strings), so one data line.
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n".encode()


async def sse_frames(
    events: AsyncGenerator[tuple[str, BaseModel | None], None],
) -> AsyncIterator[bytes]:
    # aclosing: a disconnect while a frame is being sent still runs the events' cleanup now
    # (cancel generation, record the run as cancelled), not whenever the generator is collected.
    async with aclosing(events) as stream:
        async for event, payload in stream:
            yield frame(event, payload)
