from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    uri: str
    size_bytes: int


class ObjectStoragePort(Protocol):
    async def save(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject: ...

    async def read(self, uri: str) -> bytes: ...

    async def model_url(self, uri: str) -> str | None: ...


