from pathlib import Path

import anyio

from yongge_online.storage.ports import StoredObject


class LocalObjectStorage:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()

    def _path_for_uri(self, uri: str) -> Path:
        candidate = (self.base_dir.parent / uri).resolve()
        if candidate != self.base_dir and self.base_dir not in candidate.parents:
            raise ValueError("storage uri escapes configured upload directory")
        return candidate

    async def save(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        del content_type
        path = (self.base_dir / key).resolve()
        if self.base_dir not in path.parents:
            raise ValueError("storage key escapes configured upload directory")
        async_path = anyio.Path(path)
        await async_path.parent.mkdir(parents=True, exist_ok=True)
        await async_path.write_bytes(content)
        uri = str(Path(self.base_dir.name) / key).replace("\\", "/")
        return StoredObject(uri=uri, size_bytes=len(content))

    async def read(self, uri: str) -> bytes:
        return await anyio.Path(self._path_for_uri(uri)).read_bytes()

    async def model_url(self, uri: str) -> str | None:
        del uri
        return None


