from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="YONGGE_",
        extra="ignore",
    )

    app_name: str = "yongge-online-api"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./data/yongge_online.db"
    upload_dir: Path = Path("uploads")
    max_upload_mb: int = Field(default=50, gt=0, le=2048)

    dashscope_api_key: SecretStr | None = None
    dashscope_host: str | None = None
    qwen_video_model: str = "qwen3.5-omni-plus"
    qwen_agent_model: str = "qwen3.7-plus"
    qwen_realtime_model: str = "qwen3.5-omni-flash-realtime"
    qwen_asr_model: str = "qwen3-asr-flash-realtime"
    # 实时连麦音色:优先餐饮专家复刻音色(需授权,见 PRD 纪律);未配置/失效时兜底男声预置音色
    qwen_realtime_voice: str | None = None
    qwen_realtime_fallback_voice: str = "Ethan"
    asr_max_seconds: int = Field(default=60, gt=0, le=180)

    amap_web_service_key: SecretStr | None = None
    public_base_url: str | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    external_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    @property
    def dashscope_openai_base_url(self) -> str | None:
        if not self.dashscope_host:
            return None
        return f"https://{self.dashscope_host}/compatible-mode/v1"

    @property
    def dashscope_realtime_ws_url(self) -> str | None:
        if not self.dashscope_host:
            return None
        return (
            f"wss://{self.dashscope_host}/api-ws/v1/realtime"
            f"?model={self.qwen_realtime_model}"
        )

    @property
    def dashscope_asr_ws_url(self) -> str | None:
        if not self.dashscope_host:
            return None
        return (
            f"wss://{self.dashscope_host}/api-ws/v1/realtime"
            f"?model={self.qwen_asr_model}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


