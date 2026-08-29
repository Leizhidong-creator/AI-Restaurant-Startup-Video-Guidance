import os

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts.realtime_probe import probe
from yongge_online.ai.qwen import (
    DashScopeTemporaryFileUploader,
    QwenReportGenerator,
    QwenVideoUnderstanding,
)
from yongge_online.core.config import Settings
from yongge_online.main import create_app

SAMPLE_VIDEO_URL = (
    "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/"
    "zh-CN/20241115/cqqkru/1.mp4"
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1",
        reason="set RUN_LIVE_TESTS=1 to call paid Qwen APIs",
    ),
]


def live_settings() -> Settings:
    settings = Settings(_env_file=None, external_timeout_seconds=180)
    if not settings.dashscope_api_key or not settings.dashscope_openai_base_url:
        pytest.skip("missing YONGGE_DASHSCOPE_API_KEY or YONGGE_DASHSCOPE_HOST")
    return settings


@pytest.mark.asyncio
async def test_qwen_agent_generates_structured_report() -> None:
    settings = live_settings()
    provider = QwenReportGenerator(
        api_key=settings.dashscope_api_key.get_secret_value(),
        base_url=settings.dashscope_openai_base_url,
        model=settings.qwen_agent_model,
        timeout_seconds=settings.external_timeout_seconds,
    )
    report = await provider.generate_report(
        context={
            "session_id": "live-session",
            "store": {
                "name": "测试奶茶店",
                "category": "奶茶",
                "monthly_revenue": "36000",
            },
            "events": [
                {
                    "id": "event-live-1",
                    "actor": "user",
                    "payload": {"text": "最近每天营业额约 1200 元"},
                }
            ],
            "tool_calls": [
                {
                    "id": "tool-live-1",
                    "tool_name": "calculate_business_metrics",
                    "result": {
                        "monthly_profit": "-2600.00",
                        "break_even_monthly_revenue": "40000.00",
                    },
                }
            ],
            "knowledge": [
                {
                    "id": "knowledge-live-1",
                    "kind": "claim",
                    "content": "先计算保本营业额再决定整改或止损。",
                }
            ],
        }
    )

    assert report.summary
    assert report.conclusion.value in {
        "rectify",
        "observe",
        "stop_loss",
        "insufficient_data",
    }


@pytest.mark.asyncio
async def test_qwen_omni_understands_public_sample_video() -> None:
    settings = live_settings()
    provider = QwenVideoUnderstanding(
        api_key=settings.dashscope_api_key.get_secret_value(),
        base_url=settings.dashscope_openai_base_url,
        model=settings.qwen_video_model,
        timeout_seconds=settings.external_timeout_seconds,
    )
    analysis = await provider.analyze_video(
        filename="official-sample.mp4",
        content_type="video/mp4",
        content=b"",
        model_url=SAMPLE_VIDEO_URL,
    )

    assert analysis.summary


@pytest.mark.asyncio
async def test_dashscope_temporary_video_upload_round_trip() -> None:
    settings = live_settings()
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        video_response = await client.get(SAMPLE_VIDEO_URL)
    video_response.raise_for_status()
    api_key = settings.dashscope_api_key.get_secret_value()
    uploader = DashScopeTemporaryFileUploader(
        api_key=api_key,
        timeout_seconds=settings.external_timeout_seconds,
    )
    temporary_url = await uploader.upload(
        filename="official-sample.mp4",
        content_type="video/mp4",
        content=video_response.content,
        model=settings.qwen_video_model,
    )
    provider = QwenVideoUnderstanding(
        api_key=api_key,
        base_url=settings.dashscope_openai_base_url,
        model=settings.qwen_video_model,
        timeout_seconds=settings.external_timeout_seconds,
    )

    analysis = await provider.analyze_video(
        filename="official-sample.mp4",
        content_type="video/mp4",
        content=b"",
        model_url=temporary_url,
    )

    assert temporary_url.startswith("oss://")
    assert analysis.summary


@pytest.mark.asyncio
async def test_qwen_realtime_accepts_connection_and_session_update() -> None:
    live_settings()
    await probe(timeout_seconds=30)


def test_live_backend_chain_from_upload_to_non_fallback_report(tmp_path) -> None:
    base = live_settings()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'live-chain.db'}",
        upload_dir=tmp_path / "uploads",
        max_upload_mb=10,
        dashscope_api_key=base.dashscope_api_key,
        dashscope_host=base.dashscope_host,
        external_timeout_seconds=180,
    )
    video_response = httpx.get(SAMPLE_VIDEO_URL, follow_redirects=True, timeout=60)
    video_response.raise_for_status()

    with TestClient(create_app(settings)) as client:
        user_response = client.post(
            "/api/v1/users",
            json={"display_name": "真实链路验收用户", "experience_level": "novice"},
        )
        assert user_response.status_code == 201
        user_id = user_response.json()["id"]

        store_response = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={
                "name": "真实链路验收门店",
                "category": "餐饮",
                "stage": "operating",
                "monthly_revenue": "36000",
                "monthly_rent": "12000",
                "monthly_labor_cost": "11000",
                "monthly_other_fixed_cost": "3000",
                "ingredient_cost_rate": "0.35",
                "operating_days_per_month": 30,
            },
        )
        assert store_response.status_code == 201
        store_id = store_response.json()["id"]

        upload_response = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("official-sample.mp4", video_response.content, "video/mp4")},
        )
        assert upload_response.status_code == 201
        video_id = upload_response.json()["id"]

        analysis_response = client.post(f"/api/v1/videos/{video_id}/analyze")
        assert analysis_response.status_code == 200, analysis_response.text
        assert analysis_response.json()["status"] == "completed"
        assert client.get(f"/api/v1/stores/{store_id}/knowledge").json()

        session_response = client.post(f"/api/v1/stores/{store_id}/sessions")
        assert session_response.status_code == 201
        session_id = session_response.json()["id"]
        event_response = client.post(
            f"/api/v1/sessions/{session_id}/events",
            json={
                "event_type": "transcript",
                "actor": "user",
                "payload": {"text": "请结合视频资料和门店数据给出整改或止损建议。"},
            },
        )
        assert event_response.status_code == 201

        metrics_response = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "live-metrics",
                "tool_name": "calculate_business_metrics",
                "arguments": {},
            },
        )
        assert metrics_response.status_code == 200
        assert metrics_response.json()["result"]["available"] is True

        retrieval_response = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "live-retrieval",
                "tool_name": "retrieve_private_knowledge",
                "arguments": {"query": "经营 建议 风险", "limit": 5},
            },
        )
        assert retrieval_response.status_code == 200

        report_response = client.post(f"/api/v1/sessions/{session_id}/complete")
        assert report_response.status_code == 200
        assert report_response.json()["is_fallback"] is False, report_response.text
        assert report_response.json()["report"]["summary"]


