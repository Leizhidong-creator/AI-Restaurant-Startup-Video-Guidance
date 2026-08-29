import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from yongge_online.core.config import Settings
from yongge_online.main import create_app


class FakeUpstream:
    def __init__(self) -> None:
        import asyncio

        self.events: list[dict] = []
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def send(self, raw: str) -> None:
        event = json.loads(raw)
        self.events.append(event)
        if event["type"] == "input_audio_buffer.append":
            await self.queue.put(
                json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.text",
                        "text": "我想在",
                        "stash": "武汉开店",
                    }
                )
            )
        elif event["type"] == "input_audio_buffer.commit":
            await self.queue.put(
                json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.completed",
                        "transcript": "我想在武汉开店",
                    }
                )
            )
        elif event["type"] == "session.finish":
            await self.queue.put(json.dumps({"type": "session.finished"}))
            await self.queue.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


class FakeConnector:
    def __init__(self, upstream: FakeUpstream) -> None:
        self.upstream = upstream
        self.url: str | None = None
        self.kwargs: dict = {}

    def __call__(self, url: str, **kwargs):
        self.url = url
        self.kwargs = kwargs
        return self

    async def __aenter__(self) -> FakeUpstream:
        return self.upstream

    async def __aexit__(self, *_args) -> None:
        return None


def build_app(tmp_path, connector: FakeConnector):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'asr.db'}",
        upload_dir=tmp_path / "uploads",
        dashscope_api_key=SecretStr("test-key"),
        dashscope_host="example.invalid",
        public_base_url="https://pocketmentor.icu",
        cors_origins=["http://localhost:5173"],
    )
    return create_app(settings, asr_connector=connector)


def test_asr_proxy_forwards_pcm_and_normalizes_transcript(tmp_path) -> None:
    upstream = FakeUpstream()
    connector = FakeConnector(upstream)

    with TestClient(build_app(tmp_path, connector)) as client:
        with client.websocket_connect(
            "/api/v1/asr/stream", headers={"origin": "https://pocketmentor.icu"}
        ) as websocket:
            assert websocket.receive_json() == {"type": "ready"}
            websocket.send_bytes(b"\x01\x02\x03\x04")
            assert websocket.receive_json() == {
                "type": "partial",
                "confirmed": "我想在",
                "draft": "武汉开店",
            }
            websocket.send_json({"type": "commit"})
            assert websocket.receive_json() == {"type": "final", "text": "我想在武汉开店"}
            assert websocket.receive_json() == {"type": "closed"}

    assert connector.url == (
        "wss://example.invalid/api-ws/v1/realtime?model=qwen3-asr-flash-realtime"
    )
    assert connector.kwargs["additional_headers"] == {"Authorization": "Bearer test-key"}
    assert [event["type"] for event in upstream.events] == [
        "session.update",
        "input_audio_buffer.append",
        "input_audio_buffer.commit",
        "session.finish",
    ]
    assert upstream.events[0]["session"]["turn_detection"] is None
    assert upstream.events[0]["session"]["sample_rate"] == 16_000


def test_asr_proxy_rejects_unknown_origin(tmp_path) -> None:
    connector = FakeConnector(FakeUpstream())

    with TestClient(build_app(tmp_path, connector)) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/api/v1/asr/stream", headers={"origin": "https://attacker.example"}
            ):
                pass

    assert exc_info.value.code == 1008
    assert connector.url is None


