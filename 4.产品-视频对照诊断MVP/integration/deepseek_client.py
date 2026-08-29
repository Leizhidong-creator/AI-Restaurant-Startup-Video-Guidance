"""DeepSeek 适配器:产出 reasoning.py 需要的 model_call(prompt)->str。

OpenAI 兼容 chat/completions + JSON 模式。key 从仓库根 .env 或环境变量读,绝不打印/落盘。
仅标准库,无第三方依赖。
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


def _load_env() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]  # 仓库根
    envf = root / ".env"
    vals: dict[str, str] = {}
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def make_deepseek_model_call(*, temperature: float = 0.3, timeout: int = 90):
    env = _load_env()
    key = os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置(仓库根 .env 或环境变量)")
    base = (os.environ.get("DEEPSEEK_BASE_URL") or env.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL") or env.get("DEEPSEEK_MODEL") or "deepseek-chat"
    url = f"{base}/chat/completions"

    def model_call(prompt: str) -> str:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    return model_call


