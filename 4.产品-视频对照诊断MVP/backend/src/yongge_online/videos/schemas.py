from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VideoStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class VideoLinkRelevance(StrEnum):
    RELEVANT = "relevant"
    LOW = "low"
    UNCERTAIN = "uncertain"


class VideoLinkRelevanceResult(BaseModel):
    relevance: VideoLinkRelevance
    reason: str = Field(min_length=1, max_length=120)


class VideoUrlPreviewRead(BaseModel):
    title: str
    description: str | None = None
    relevance: VideoLinkRelevance
    reason: str


class VideoSourceStatusRead(BaseModel):
    status: str
    cookie_file_configured: bool
    last_resolution_at: datetime | None
    last_selected_provider: str | None
    last_primary_failure_reason: str | None
    resolutions_24h: int
    fallbacks_24h: int
    cookie_failures_24h: int


class TransferVerdict(StrEnum):
    """个体迁移四档判断（PRD §8.8：可学 / 需改 / 不可照搬 / 待验证）。"""

    LEARNABLE = "learnable"
    ADAPT_REQUIRED = "adapt_required"
    NOT_REPLICABLE = "not_replicable"
    TO_VERIFY = "to_verify"


class DimensionEvidence(BaseModel):
    content: str = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)


class DimensionInsight(BaseModel):
    why_it_works: str = Field(min_length=1)
    evidence: list[DimensionEvidence] = Field(default_factory=list)
    transfer: TransferVerdict
    transfer_reason: str = Field(min_length=1)


class CaseDeconstruction(BaseModel):
    location: DimensionInsight
    product: DimensionInsight
    audience: DimensionInsight
    operation: DimensionInsight
    overall_note: str | None = None


class DeconstructionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    result_json: dict[str, Any]
    is_fallback: bool
    created_at: datetime


class VideoAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    store_id: str
    filename: str
    content_type: str
    size_bytes: int
    storage_uri: str
    sha256: str
    status: VideoStatus
    error_code: str | None
    error_message: str | None
    analysis_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


