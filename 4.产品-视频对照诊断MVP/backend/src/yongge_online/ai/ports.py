from typing import Any, Protocol

from pydantic import BaseModel, Field

from yongge_online.videos.schemas import VideoLinkRelevanceResult


class TranscriptSegment(BaseModel):
    speaker: str | None = None
    text: str = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class ExtractedKnowledge(BaseModel):
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class VideoAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    claims: list[ExtractedKnowledge] = Field(default_factory=list)
    risks: list[ExtractedKnowledge] = Field(default_factory=list)
    cases: list[ExtractedKnowledge] = Field(default_factory=list)
    actions: list[ExtractedKnowledge] = Field(default_factory=list)


class VideoUnderstandingPort(Protocol):
    async def analyze_video(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        model_url: str | None,
    ) -> VideoAnalysis: ...


class VideoLinkRelevancePort(Protocol):
    async def check_link_metadata(
        self, *, title: str, description: str | None
    ) -> VideoLinkRelevanceResult: ...


class ReportGeneratorPort(Protocol):
    async def generate_report(self, *, context: dict[str, Any]): ...


class CaseDeconstructorPort(Protocol):
    async def deconstruct_case(self, *, context: dict[str, Any]): ...


