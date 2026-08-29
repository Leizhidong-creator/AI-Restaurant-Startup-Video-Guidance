from fastapi.testclient import TestClient

from yongge_online.ai.ports import ExtractedKnowledge, VideoAnalysis
from yongge_online.core.config import Settings
from yongge_online.main import create_app


class FakeVideoUnderstanding:
    def __init__(self) -> None:
        self.call_count = 0

    async def analyze_video(self, **_kwargs) -> VideoAnalysis:
        self.call_count += 1
        return VideoAnalysis(
            summary="视频指出门店收入不足且固定成本偏高。",
            transcript=[
                {
                    "speaker": "餐饮专家",
                    "text": "先算每天保本营业额，再决定整改还是止损。",
                    "start_ms": 1200,
                    "end_ms": 5800,
                }
            ],
            claims=[
                ExtractedKnowledge(
                    content="诊断亏损门店应先计算保本营业额。",
                    tags=["保本点", "亏损"],
                    start_ms=1200,
                    end_ms=5800,
                    confidence=0.95,
                )
            ],
            risks=[
                ExtractedKnowledge(
                    content="高房租和低营业额叠加会快速消耗现金流。",
                    tags=["房租", "现金流"],
                    confidence=0.9,
                )
            ],
            cases=[],
            actions=[
                ExtractedKnowledge(
                    content="连续七天记录营业额、订单数和客单价。",
                    tags=["行动", "数据记录"],
                    confidence=0.92,
                )
            ],
        )


class FailingVideoUnderstanding:
    async def analyze_video(self, **_kwargs) -> VideoAnalysis:
        raise RuntimeError("provider returned malformed output")


def build_client(tmp_path, provider) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'analysis.db'}",
        upload_dir=tmp_path / "uploads",
    )
    return TestClient(create_app(settings, video_provider=provider))


def upload_asset(client: TestClient) -> tuple[str, str]:
    user_id = client.post(
        "/api/v1/users",
        json={"display_name": "解析用户", "experience_level": "novice"},
    ).json()["id"]
    store_id = client.post(
        f"/api/v1/users/{user_id}/stores",
        json={"name": "解析门店", "category": "奶茶", "stage": "operating"},
    ).json()["id"]
    video_id = client.post(
        f"/api/v1/stores/{store_id}/videos",
        files={"file": ("advice.mp4", b"\x00\x00\x00\x18ftypmp42demo", "video/mp4")},
    ).json()["id"]
    return store_id, video_id


def test_analysis_populates_private_knowledge_atomically(tmp_path) -> None:
    with build_client(tmp_path, FakeVideoUnderstanding()) as client:
        store_id, video_id = upload_asset(client)

        response = client.post(f"/api/v1/videos/{video_id}/analyze")

        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["analysis_json"]["summary"].startswith("视频指出")

        knowledge = client.get(f"/api/v1/stores/{store_id}/knowledge").json()
        assert {item["kind"] for item in knowledge} == {
            "summary",
            "transcript",
            "claim",
            "risk",
            "action",
        }
        assert all(item["source_id"] == video_id for item in knowledge)


def test_reanalyzing_completed_video_skips_provider(tmp_path) -> None:
    provider = FakeVideoUnderstanding()
    with build_client(tmp_path, provider) as client:
        _store_id, video_id = upload_asset(client)

        first = client.post(f"/api/v1/videos/{video_id}/analyze")
        second = client.post(f"/api/v1/videos/{video_id}/analyze")

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["analysis_json"] == first.json()["analysis_json"]
        assert provider.call_count == 1


def test_same_content_reupload_reuses_cached_analysis(tmp_path) -> None:
    provider = FakeVideoUnderstanding()
    with build_client(tmp_path, provider) as client:
        store_id, first_video_id = upload_asset(client)
        client.post(f"/api/v1/videos/{first_video_id}/analyze")

        # 同一份内容重新上传（新的 video_id，模拟前端每次演示重传 demo 视频）
        second_video_id = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("advice.mp4", b"\x00\x00\x00\x18ftypmp42demo", "video/mp4")},
        ).json()["id"]
        response = client.post(f"/api/v1/videos/{second_video_id}/analyze")

        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert provider.call_count == 1

        # 缓存命中时仍需为新视频写入私有知识
        knowledge = client.get(f"/api/v1/stores/{store_id}/knowledge").json()
        assert any(item["source_id"] == second_video_id for item in knowledge)


def test_analysis_failure_sets_queryable_failed_state(tmp_path) -> None:
    with build_client(tmp_path, FailingVideoUnderstanding()) as client:
        _store_id, video_id = upload_asset(client)

        response = client.post(f"/api/v1/videos/{video_id}/analyze")

        assert response.status_code == 502
        asset = client.get(f"/api/v1/videos/{video_id}").json()
        assert asset["status"] == "failed"
        assert asset["error_code"] == "video_analysis_failed"
        assert "malformed output" in asset["error_message"]


