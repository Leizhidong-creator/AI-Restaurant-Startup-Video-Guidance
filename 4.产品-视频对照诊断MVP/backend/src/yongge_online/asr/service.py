import asyncio
import base64
import contextlib
import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

PCM_BYTES_PER_SECOND = 16_000 * 2


class AsrProxyService:
    """Bridge browser PCM to Qwen ASR without exposing credentials."""

    def __init__(
        self,
        *,
        api_key: str | None,
        websocket_url: str | None,
        allowed_origins: set[str],
        max_seconds: int = 60,
        timeout_seconds: float = 60,
        connector: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.websocket_url = websocket_url
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins if origin}
        self.max_seconds = max_seconds
        self.max_audio_bytes = PCM_BYTES_PER_SECOND * max_seconds
        self.timeout_seconds = timeout_seconds
        self.connector = connector or connect

    async def handle(self, client: WebSocket) -> None:
        origin = (client.headers.get("origin") or "").rstrip("/")
        if not origin or origin not in self.allowed_origins:
            await client.close(code=1008, reason="Origin not allowed")
            return

        await client.accept()
        if not self.api_key or not self.websocket_url:
            await self._send(client, {"type": "error", "message": "语音服务暂不可用"})
            await client.close(code=1011)
            return

        try:
            async with asyncio.timeout(self.max_seconds + self.timeout_seconds):
                async with self.connector(
                    self.websocket_url,
                    additional_headers={"Authorization": f"Bearer {self.api_key}"},
                    open_timeout=self.timeout_seconds,
                    close_timeout=5,
                ) as upstream:
                    await upstream.send(json.dumps(self._session_update(), ensure_ascii=False))
                    await self._send(client, {"type": "ready"})

                    receive_task = asyncio.create_task(self._receive_audio(client, upstream))
                    forward_task = asyncio.create_task(self._forward_events(client, upstream))
                    done, pending = await asyncio.wait(
                        {receive_task, forward_task}, return_when=asyncio.FIRST_COMPLETED
                    )

                    receive_result = None
                    if receive_task in done:
                        receive_result = receive_task.result()
                    if forward_task in done:
                        forward_task.result()

                    if receive_result == "committed" and not forward_task.done():
                        await forward_task
                    else:
                        for task in pending:
                            task.cancel()
                        for task in pending:
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
        except WebSocketDisconnect:
            return
        except TimeoutError:
            await self._send(client, {"type": "error", "message": "语音输入时间过长，请重试"})
        except Exception:
            await self._send(client, {"type": "error", "message": "语音识别连接失败，请重试"})
        finally:
            with contextlib.suppress(RuntimeError):
                await client.close()

    def _session_update(self) -> dict[str, Any]:
        return {
            "event_id": f"event_{uuid4().hex}",
            "type": "session.update",
            "session": {
                "input_audio_format": "pcm",
                "sample_rate": 16_000,
                "input_audio_transcription": {"language": "zh"},
                "turn_detection": None,
            },
        }

    async def _receive_audio(self, client: WebSocket, upstream: Any) -> str:
        received_bytes = 0
        while True:
            message = await client.receive()
            if message["type"] == "websocket.disconnect":
                with contextlib.suppress(Exception):
                    await upstream.send(json.dumps(self._event("session.finish")))
                return "disconnected"

            audio = message.get("bytes")
            if audio is not None:
                received_bytes += len(audio)
                if received_bytes > self.max_audio_bytes:
                    await self._send(
                        client, {"type": "error", "message": "单次语音最多 60 秒"}
                    )
                    await upstream.send(json.dumps(self._event("session.finish")))
                    return "limited"
                await upstream.send(
                    json.dumps(
                        self._event(
                            "input_audio_buffer.append",
                            audio=base64.b64encode(audio).decode("ascii"),
                        )
                    )
                )
                continue

            raw_text = message.get("text")
            if raw_text is None:
                continue
            try:
                event = json.loads(raw_text)
            except json.JSONDecodeError:
                await self._send(client, {"type": "error", "message": "无效的语音指令"})
                continue

            event_type = event.get("type")
            if event_type == "commit":
                await upstream.send(json.dumps(self._event("input_audio_buffer.commit")))
                await upstream.send(json.dumps(self._event("session.finish")))
                return "committed"
            if event_type == "cancel":
                await upstream.send(json.dumps(self._event("session.finish")))
                return "cancelled"

    async def _forward_events(self, client: WebSocket, upstream: Any) -> None:
        async for raw in upstream:
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            event_type = event.get("type")
            if event_type == "conversation.item.input_audio_transcription.text":
                await self._send(
                    client,
                    {
                        "type": "partial",
                        "confirmed": event.get("text") or "",
                        "draft": event.get("stash") or "",
                    },
                )
            elif event_type == "conversation.item.input_audio_transcription.completed":
                await self._send(
                    client, {"type": "final", "text": event.get("transcript") or ""}
                )
            elif event_type in {
                "conversation.item.input_audio_transcription.failed",
                "error",
            }:
                await self._send(client, {"type": "error", "message": "没有听清，请重试"})
            elif event_type == "session.finished":
                await self._send(client, {"type": "closed"})
                return

    @staticmethod
    def _event(event_type: str, **payload: Any) -> dict[str, Any]:
        return {"event_id": f"event_{uuid4().hex}", "type": event_type, **payload}

    @staticmethod
    async def _send(client: WebSocket, payload: dict[str, Any]) -> None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await client.send_json(payload)


