import base64
import json
from pathlib import Path

import httpx
from openai import (
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from yongge_online.ai.ports import VideoAnalysis
from yongge_online.core.errors import ExternalServiceError
from yongge_online.diagnosis.prompts import REPORT_SYSTEM_PROMPT
from yongge_online.diagnosis.schemas import DiagnosisReport
from yongge_online.videos.prompts import (
    CASE_DECONSTRUCTION_SYSTEM_PROMPT,
    VIDEO_ANALYSIS_PROMPT,
    VIDEO_LINK_RELEVANCE_PROMPT,
)
from yongge_online.videos.schemas import (
    CaseDeconstruction,
    VideoLinkRelevance,
    VideoLinkRelevanceResult,
)


def qwen_service_error(service: str, exc: Exception) -> ExternalServiceError:
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return ExternalServiceError(
            service,
            "API 凭据无效、已失效或无此模型权限",
            retryable=False,
        )
    if isinstance(exc, RateLimitError):
        return ExternalServiceError(service, "请求过于频繁，请稍后重试")
    return ExternalServiceError(service, str(exc))


class DashScopeTemporaryFileUploader:
    """Upload local media to Bailian's 48-hour development storage."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        policy_url: str = "https://dashscope.aliyuncs.com/api/v1/uploads",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.policy_url = policy_url
        self.transport = transport

    async def upload(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        model: str,
    ) -> str:
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
            ) as client:
                policy_response = await client.get(
                    self.policy_url,
                    params={"action": "getPolicy", "model": model},
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                policy_response.raise_for_status()
                policy = policy_response.json()["data"]
                max_bytes = int(policy["max_file_size_mb"]) * 1024 * 1024
                if len(content) > max_bytes:
                    raise ExternalServiceError(
                        "DashScope Temporary Storage",
                        f"视频超过模型临时上传上限 {policy['max_file_size_mb']} MB",
                        retryable=False,
                    )
                safe_filename = Path(filename).name or "video"
                object_key = f"{policy['upload_dir'].rstrip('/')}/{safe_filename}"
                upload_response = await client.post(
                    policy["upload_host"],
                    data={
                        "OSSAccessKeyId": policy["oss_access_key_id"],
                        "policy": policy["policy"],
                        "Signature": policy["signature"],
                        "key": object_key,
                        "x-oss-object-acl": policy["x_oss_object_acl"],
                        "x-oss-forbid-overwrite": policy[
                            "x_oss_forbid_overwrite"
                        ],
                        "success_action_status": "200",
                    },
                    files={"file": (safe_filename, content, content_type)},
                )
                upload_response.raise_for_status()
                return f"oss://{object_key}"
        except ExternalServiceError:
            raise
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                raise ExternalServiceError(
                    "DashScope Temporary Storage",
                    "API 凭据无效、已失效或无此模型权限",
                    retryable=False,
                ) from exc
            raise ExternalServiceError(
                "DashScope Temporary Storage",
                f"返回 HTTP {status_code}",
                retryable=status_code == 429 or status_code >= 500,
            ) from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceError(
                "DashScope Temporary Storage",
                str(exc),
            ) from exc


def parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        cleaned = cleaned[first_newline + 1 :] if first_newline >= 0 else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response does not contain a JSON object")
    return json.loads(cleaned[start : end + 1])


class UnavailableVideoUnderstanding:
    async def analyze_video(self, **_kwargs) -> VideoAnalysis:
        raise ExternalServiceError("Qwen Video", "未配置百炼 API Key 或 API Host")


class UnavailableVideoLinkRelevanceChecker:
    async def check_link_metadata(
        self, *, title: str, description: str | None
    ) -> VideoLinkRelevanceResult:
        del title, description
        return VideoLinkRelevanceResult(
            relevance=VideoLinkRelevance.UNCERTAIN,
            reason="暂时无法判断，继续由用户决定",
        )


class QwenVideoLinkRelevanceChecker:
    def __init__(
        self, *, api_key: str, base_url: str, model: str, timeout_seconds: float
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
        )
        self.model = model

    async def check_link_metadata(
        self, *, title: str, description: str | None
    ) -> VideoLinkRelevanceResult:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": VIDEO_LINK_RELEVANCE_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "title": title[:200],
                                "description": (description or "")[:500],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
            content = response.choices[0].message.content or ""
            return VideoLinkRelevanceResult.model_validate(parse_json_object(content))
        except Exception as exc:
            raise qwen_service_error("Qwen Link Relevance", exc) from exc


class QwenVideoUnderstanding:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temporary_uploader: DashScopeTemporaryFileUploader | None = None,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
        )
        self.model = model
        self.temporary_uploader = temporary_uploader or DashScopeTemporaryFileUploader(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    async def analyze_video(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        model_url: str | None,
    ) -> VideoAnalysis:
        try:
            if model_url:
                video_url = model_url
            elif len(content) > 7_500_000:
                video_url = await self.temporary_uploader.upload(
                    filename=filename,
                    content_type=content_type,
                    content=content,
                    model=self.model,
                )
            else:
                encoded = base64.b64encode(content).decode("ascii")
                video_url = f"data:{content_type};base64,{encoded}"

            request = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "video_url", "video_url": {"url": video_url}},
                            {"type": "text", "text": VIDEO_ANALYSIS_PROMPT},
                        ],
                    }
                ],
                "modalities": ["text"],
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if video_url.startswith("oss://"):
                request["extra_headers"] = {
                    "X-DashScope-OssResourceResolve": "enable"
                }
            stream = await self.client.chat.completions.create(**request)
            chunks: list[str] = []
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            return VideoAnalysis.model_validate(parse_json_object("".join(chunks)))
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise qwen_service_error("Qwen Video", exc) from exc


class UnavailableReportGenerator:
    async def generate_report(self, *, context: dict) -> DiagnosisReport:
        del context
        raise ExternalServiceError("Qwen Report", "未配置百炼 API Key 或 API Host")


class QwenReportGenerator:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
        )
        self.model = model

    async def generate_report(self, *, context: dict) -> DiagnosisReport:
        try:
            output_schema = json.dumps(
                DiagnosisReport.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "请根据业务上下文生成经营诊断报告。输出必须严格符合下方 "
                            "JSON Schema，不得增加 schema 外字段。evidence_refs.source_id "
                            "只能原样引用业务上下文中存在的 id。\nJSON Schema：\n"
                            + output_schema
                            + "\n业务上下文：\n"
                            + json.dumps(context, ensure_ascii=False)
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
            content = response.choices[0].message.content or ""
            return DiagnosisReport.model_validate(parse_json_object(content))
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise qwen_service_error("Qwen Report", exc) from exc


class UnavailableCaseDeconstructor:
    async def deconstruct_case(self, *, context: dict) -> CaseDeconstruction:
        del context
        raise ExternalServiceError("Qwen Deconstruction", "未配置百炼 API Key 或 API Host")


class QwenCaseDeconstructor:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
        )
        self.model = model

    async def deconstruct_case(self, *, context: dict) -> CaseDeconstruction:
        try:
            output_schema = json.dumps(
                CaseDeconstruction.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CASE_DECONSTRUCTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "请解构下方案例并给出四维迁移初判。输出必须严格符合下方 "
                            "JSON Schema，不得增加 schema 外字段。evidence.content "
                            "只能逐字引用「视频证据」中的 content。\nJSON Schema：\n"
                            + output_schema
                            + "\n业务上下文：\n"
                            + json.dumps(context, ensure_ascii=False)
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
            content = response.choices[0].message.content or ""
            return CaseDeconstruction.model_validate(parse_json_object(content))
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise qwen_service_error("Qwen Deconstruction", exc) from exc


