from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    store_id: str
    source_type: str
    source_id: str
    kind: str
    content: str
    tags_json: list[str]
    start_ms: int | None
    end_ms: int | None
    confidence: float | None
    created_at: datetime


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)


class KnowledgeHit(BaseModel):
    id: str
    kind: str
    content: str
    tags: list[str]
    start_ms: int | None
    end_ms: int | None
    score: float
    scope: str = "private"
    source_type: str | None = None
    source_id: str | None = None
    source_uri: str | None = None
    review_status: str | None = None
    knowledge_id: str | None = None
    version: str | None = None
    evidence_grade: str | None = None


class PlatformKnowledgeUpsert(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    knowledge_id: str | None = Field(default=None, max_length=120)
    version: str = Field(default="1", min_length=1, max_length=30)
    title: str | None = Field(default=None, max_length=255)
    source_type: str = Field(min_length=1, max_length=50)
    source_id: str = Field(min_length=1, max_length=255)
    source_uri: str | None = None
    source_locator: str | None = None
    published_at: str | None = None
    kind: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    applicable_categories: list[str] = Field(default_factory=list)
    business_stages: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    risk_level: str = "unknown"
    review_status: str = "draft"
    evidence_grade: str | None = None
    reviewed_by: str | None = Field(default=None, max_length=120)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class KnowledgeSearchResponse(BaseModel):
    hits: list[KnowledgeHit]


