"""Shared fixtures for the literature/document tool tests (no network access)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx2

from app.tools.literature.models import Paper, SourceRef

PUBLIC_IP = "93.184.215.14"


async def public_resolver(host: str, port: int) -> list[str]:
    return [PUBLIC_IP]


def make_resolver(mapping: dict[str, list[str]]) -> Any:
    async def resolve(host: str, port: int) -> list[str]:
        return mapping.get(host, [PUBLIC_IP])

    return resolve


class ChunkStream(httpx2.AsyncByteStream):
    """Streams `total` bytes in chunks and records how much was actually consumed."""

    def __init__(self, total: int, chunk: int = 64 * 1024, prefix: bytes = b"%PDF-1.4\n") -> None:
        self.total, self.chunk, self.prefix, self.sent = total, chunk, prefix, 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        first = True
        while self.sent < self.total:
            size = min(self.chunk, self.total - self.sent)
            data = (self.prefix + b"0" * size)[:size] if first else b"0" * size
            first = False
            self.sent += size
            yield data


def paper(
    title: str = "Sleep deprivation impairs memory consolidation in adults",
    *,
    source: str = "openalex",
    source_id: str = "W1",
    rank: int = 1,
    **fields: Any,
) -> Paper:
    ids = {"openalex": "openalex_id", "semantic_scholar": "semantic_scholar_id"}
    fields.setdefault(ids[source], source_id)
    return Paper(
        title=title,
        sources=[SourceRef(source=source, source_id=source_id, rank=rank)],
        **fields,
    )
