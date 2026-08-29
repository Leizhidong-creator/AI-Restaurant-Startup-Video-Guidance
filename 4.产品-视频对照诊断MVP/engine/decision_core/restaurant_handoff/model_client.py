from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping


class ModelServiceError(RuntimeError):
    pass


class OpenAICompatibleJsonClient:
    """Minimal JSON-only chat client for OpenAI-compatible model endpoints."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_seconds: int = 45,
        temperature: float = 0,
        use_json_mode: bool = True,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not base_url:
            raise ValueError("base_url is required")
        if not model_name:
            raise ValueError("model_name is required")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.use_json_mode = use_json_mode
        self._opener = opener

    @classmethod
    def from_env(cls, prefix: str = "RESTAURANT_MODEL") -> "OpenAICompatibleJsonClient":
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        base_url = os.environ.get(
            f"{prefix}_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        model_name = os.environ.get(f"{prefix}_NAME", "")
        missing = [
            name
            for name, value in (
                (f"{prefix}_API_KEY", api_key),
                (f"{prefix}_NAME", model_name),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"missing environment variables: {', '.join(missing)}")
        return cls(api_key=api_key, base_url=base_url, model_name=model_name)

    def __call__(self, prompt: str) -> Mapping[str, Any]:
        return self.complete_json(prompt)

    def complete_json(
        self,
        prompt: str,
        *,
        system_instruction: str = "Return one valid JSON object and no other text.",
    ) -> Mapping[str, Any]:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }
        if self.use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ModelServiceError(f"model service returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelServiceError(
                f"model service unavailable: {type(exc).__name__}"
            ) from exc
        try:
            body = json.loads(raw_body)
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content must be a string")
            value = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelServiceError("model response is not a valid JSON object") from exc
        if not isinstance(value, Mapping):
            raise ModelServiceError("model response is not a valid JSON object")
        return value


