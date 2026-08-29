from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import ModelServiceError, OpenAICompatibleJsonClient


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


class ModelClientTest(unittest.TestCase):
    def test_json_client_sends_compatible_request(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "fact_key": "location",
                                        "question": "地址在哪里？",
                                        "rationale": "核验位置",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
            )

        client = OpenAICompatibleJsonClient(
            api_key="secret-for-test",
            base_url="https://model.example/v1/",
            model_name="model-test",
            opener=opener,
        )
        value = client("choose one question")
        self.assertEqual(value["fact_key"], "location")
        self.assertEqual(captured["url"], "https://model.example/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "model-test")
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})

    def test_invalid_model_content_is_rejected(self) -> None:
        client = OpenAICompatibleJsonClient(
            api_key="secret-for-test",
            base_url="https://model.example/v1",
            model_name="model-test",
            opener=lambda request, timeout: FakeResponse(
                {"choices": [{"message": {"content": "not-json"}}]}
            ),
        )
        with self.assertRaises(ModelServiceError):
            client("choose one question")

    def test_json_array_is_rejected(self) -> None:
        client = OpenAICompatibleJsonClient(
            api_key="secret-for-test",
            base_url="https://model.example/v1",
            model_name="model-test",
            opener=lambda request, timeout: FakeResponse(
                {"choices": [{"message": {"content": "[]"}}]}
            ),
        )
        with self.assertRaises(ModelServiceError):
            client("choose one question")

    def test_from_env_requires_key_and_model_name(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "RESTAURANT_MODEL_API_KEY"):
                OpenAICompatibleJsonClient.from_env()


if __name__ == "__main__":
    unittest.main()


