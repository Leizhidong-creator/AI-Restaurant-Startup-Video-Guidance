from typing import Any

from pydantic import BaseModel


class RealtimeConfig(BaseModel):
    model: str
    sdp_endpoint: str
    session_update: dict[str, Any]


