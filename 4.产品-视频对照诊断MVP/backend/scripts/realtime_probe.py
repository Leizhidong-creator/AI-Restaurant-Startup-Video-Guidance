"""Connect to Qwen Realtime without sending microphone or camera data."""

import argparse
import asyncio
import json

from websockets.asyncio.client import connect

from yongge_online.core.config import get_settings


async def probe(timeout_seconds: float) -> None:
    settings = get_settings()
    if not settings.dashscope_api_key or not settings.dashscope_realtime_ws_url:
        raise SystemExit("Missing YONGGE_DASHSCOPE_API_KEY or YONGGE_DASHSCOPE_HOST")

    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key.get_secret_value()}"
    }
    async with connect(
        settings.dashscope_realtime_ws_url,
        additional_headers=headers,
        open_timeout=timeout_seconds,
    ) as websocket:
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
        event = json.loads(raw)
        if event.get("type") != "session.created":
            raise RuntimeError(f"Unexpected first event: {event.get('type', 'unknown')}")
        print("Realtime connection: session.created")
        await websocket.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "instructions": "连接探针：只确认会话配置，不发送用户媒体。",
                        "modalities": ["text"],
                    },
                },
                ensure_ascii=False,
            )
        )
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
            event = json.loads(raw)
            event_type = event.get("type", "unknown")
            print(f"Realtime connection: {event_type}")
            if event_type in {"session.updated", "error"}:
                if event_type == "error":
                    raise RuntimeError("Realtime service returned an error event")
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    asyncio.run(probe(args.timeout))


if __name__ == "__main__":
    main()


