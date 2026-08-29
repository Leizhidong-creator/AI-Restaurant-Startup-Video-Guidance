import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError

from yongge_online.ai import qwen
from yongge_online.ai.qwen import QwenReportGenerator, QwenVideoUnderstanding
from yongge_online.core.errors import ExternalServiceError
from yongge_online.diagnosis.schemas import DiagnosisReport


class CapturingCompletions:
    def __init__(self) -> None:
        self.request: dict | None = None

    async def create(self, **kwargs):
        self.request = kwargs
        payload = {
            "summary": "缺少足够证据，暂不做经营结论。",
            "conclusion": "insufficient_data",
            "confidence": 0,
            "problems": [],
            "immediate_actions": [],
            "short_term_actions": [],
            "observation_metrics": [],
            "information_gaps": ["缺少经营数据"],
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )


class OneChunkStream:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.sent = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.sent:
            raise StopAsyncIteration
        self.sent = True
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))
                )
            ]
        )


class CapturingVideoCompletions:
    def __init__(self) -> None:
        self.request: dict | None = None

    async def create(self, **kwargs):
        self.request = kwargs
        return OneChunkStream(
            {
                "summary": "视频内容已解析。",
                "transcript": [],
                "claims": [],
                "risks": [],
                "cases": [],
                "actions": [],
            }
        )


class CapturingUploader:
    def __init__(self) -> None:
        self.request: dict | None = None

    async def upload(self, **kwargs) -> str:
        content = kwargs.pop("content")
        self.request = {**kwargs, "content_size": len(content)}
        return "oss://dashscope-instant/account/request/large.mp4"


class AuthenticationFailingCompletions:
    async def create(self, **_kwargs):
        response = httpx.Response(
            401,
            request=httpx.Request("POST", "https://workspace.example.test/chat"),
        )
        raise AuthenticationError(
            "raw vendor authentication detail",
            response=response,
            body={"code": "invalid_api_key"},
        )


@pytest.mark.asyncio
async def test_qwen_report_request_contains_the_exact_output_schema() -> None:
    provider = QwenReportGenerator(
        api_key="test-key",
        base_url="https://example.test/compatible-mode/v1",
        model="qwen3.7-plus",
        timeout_seconds=10,
    )
    completions = CapturingCompletions()
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    report = await provider.generate_report(
        context={
            "session_id": "session-1",
            "store": {},
            "events": [],
            "tool_calls": [],
            "knowledge": [],
        }
    )

    assert report.conclusion.value == "insufficient_data"
    assert completions.request is not None
    user_prompt = completions.request["messages"][1]["content"]
    assert '"evidence_refs"' in user_prompt
    assert '"information_gaps"' in user_prompt
    assert DiagnosisReport.model_json_schema()["required"]


@pytest.mark.asyncio
async def test_temporary_uploader_gets_policy_and_uploads_private_video() -> None:
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "authorization": request.headers.get("authorization"),
                "content_type": request.headers.get("content-type"),
                "body": body,
            }
        )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "policy": "signed-policy",
                        "signature": "signed-value",
                        "upload_dir": "dashscope-instant/account/request",
                        "upload_host": "https://upload.example.test",
                        "max_file_size_mb": "100",
                        "oss_access_key_id": "temporary-access-key",
                        "x_oss_object_acl": "private",
                        "x_oss_forbid_overwrite": "true",
                    }
                },
            )
        return httpx.Response(200)

    uploader = qwen.DashScopeTemporaryFileUploader(
        api_key="workspace-secret",
        timeout_seconds=10,
        policy_url="https://policy.example.test/api/v1/uploads",
        transport=httpx.MockTransport(handler),
    )

    result = await uploader.upload(
        filename="经营诊断.mp4",
        content_type="video/mp4",
        content=b"large-video-content",
        model="qwen3.5-omni-plus",
    )

    assert result == (
        "oss://dashscope-instant/account/request/经营诊断.mp4"
    )
    assert requests[0] == {
        "method": "GET",
        "url": (
            "https://policy.example.test/api/v1/uploads"
            "?action=getPolicy&model=qwen3.5-omni-plus"
        ),
        "authorization": "Bearer workspace-secret",
        "content_type": "application/json",
        "body": b"",
    }
    assert requests[1]["method"] == "POST"
    assert requests[1]["url"] == "https://upload.example.test"
    assert requests[1]["authorization"] is None
    assert requests[1]["content_type"].startswith("multipart/form-data; boundary=")
    for expected in (
        b"temporary-access-key",
        b"signed-policy",
        b"signed-value",
        "经营诊断.mp4".encode(),
        b"large-video-content",
    ):
        assert expected in requests[1]["body"]


@pytest.mark.asyncio
async def test_large_video_uses_temporary_url_and_resource_resolve_header() -> None:
    uploader = CapturingUploader()
    provider = QwenVideoUnderstanding(
        api_key="workspace-secret",
        base_url="https://workspace.example.test/compatible-mode/v1",
        model="qwen3.5-omni-plus",
        timeout_seconds=10,
        temporary_uploader=uploader,
    )
    completions = CapturingVideoCompletions()
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    analysis = await provider.analyze_video(
        filename="large.mp4",
        content_type="video/mp4",
        content=b"x" * 7_500_001,
        model_url=None,
    )

    assert analysis.summary == "视频内容已解析。"
    assert uploader.request == {
        "filename": "large.mp4",
        "content_type": "video/mp4",
        "model": "qwen3.5-omni-plus",
        "content_size": 7_500_001,
    }
    assert completions.request is not None
    video_part = completions.request["messages"][0]["content"][0]
    assert video_part["video_url"]["url"].startswith("oss://")
    assert completions.request["extra_headers"] == {
        "X-DashScope-OssResourceResolve": "enable"
    }


@pytest.mark.asyncio
async def test_temporary_uploader_rejects_file_above_policy_limit() -> None:
    upload_attempted = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_attempted
        if request.method == "POST":
            upload_attempted = True
            return httpx.Response(200)
        return httpx.Response(
            200,
            json={
                "data": {
                    "policy": "signed-policy",
                    "signature": "signed-value",
                    "upload_dir": "dashscope-instant/account/request",
                    "upload_host": "https://upload.example.test",
                    "max_file_size_mb": "1",
                    "oss_access_key_id": "temporary-access-key",
                    "x_oss_object_acl": "private",
                    "x_oss_forbid_overwrite": "true",
                }
            },
        )

    uploader = qwen.DashScopeTemporaryFileUploader(
        api_key="workspace-secret",
        timeout_seconds=10,
        policy_url="https://policy.example.test/api/v1/uploads",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ExternalServiceError) as error:
        await uploader.upload(
            filename="too-large.mp4",
            content_type="video/mp4",
            content=b"x" * (1024 * 1024 + 1),
            model="qwen3.5-omni-plus",
        )

    assert error.value.retryable is False
    assert "1 MB" in error.value.message
    assert upload_attempted is False


@pytest.mark.asyncio
async def test_temporary_uploader_marks_auth_failure_non_retryable() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "InvalidApiKey"})

    uploader = qwen.DashScopeTemporaryFileUploader(
        api_key="must-not-appear-in-errors",
        timeout_seconds=10,
        policy_url="https://policy.example.test/api/v1/uploads",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ExternalServiceError) as error:
        await uploader.upload(
            filename="video.mp4",
            content_type="video/mp4",
            content=b"video",
            model="qwen3.5-omni-plus",
        )

    assert error.value.retryable is False
    assert "凭据" in error.value.message
    assert "must-not-appear-in-errors" not in error.value.message


@pytest.mark.asyncio
async def test_qwen_report_marks_auth_failure_non_retryable_and_sanitized() -> None:
    provider = QwenReportGenerator(
        api_key="must-not-appear-in-errors",
        base_url="https://workspace.example.test/compatible-mode/v1",
        model="qwen3.7-plus",
        timeout_seconds=10,
    )
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=AuthenticationFailingCompletions())
    )

    with pytest.raises(ExternalServiceError) as error:
        await provider.generate_report(context={})

    assert error.value.retryable is False
    assert "凭据" in error.value.message
    assert "raw vendor authentication detail" not in error.value.message
    assert "must-not-appear-in-errors" not in error.value.message


