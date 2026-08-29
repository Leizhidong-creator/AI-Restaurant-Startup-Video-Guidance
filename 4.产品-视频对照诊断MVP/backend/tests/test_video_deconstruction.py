from fastapi.testclient import TestClient

from tests.test_video_analysis import FakeVideoUnderstanding, upload_asset
from yongge_online.core.config import Settings
from yongge_online.main import create_app
from yongge_online.videos.schemas import (
    CaseDeconstruction,
    DimensionEvidence,
    DimensionInsight,
    TransferVerdict,
)

# FakeVideoUnderstanding 的 claims 原文,用于逐字引用
REAL_CLAIM = "诊断亏损门店应先计算保本营业额。"


def make_insight(evidence: list[DimensionEvidence]) -> DimensionInsight:
    return DimensionInsight(
        why_it_works="紧贴目标客群的自然动线，不需要顾客专门绕路。",
        evidence=evidence,
        transfer=TransferVerdict.ADAPT_REQUIRED,
        transfer_reason="预算有限，需要按自身商圈改造后借鉴。",
    )


class FakeDeconstructor:
    def __init__(self, evidence_content: str = REAL_CLAIM):
        self.call_count = 0
        self.evidence_content = evidence_content

    async def deconstruct_case(self, *, context: dict) -> CaseDeconstruction:
        self.call_count += 1
        evidence = [DimensionEvidence(content=self.evidence_content, start_ms=1200)]
        return CaseDeconstruction(
            location=make_insight(evidence),
            product=make_insight(evidence),
            audience=make_insight(evidence),
            operation=make_insight(evidence),
            overall_note=None,
        )


class FailingDeconstructor:
    async def deconstruct_case(self, *, context: dict) -> CaseDeconstruction:
        raise RuntimeError("deconstructor exploded")


def build_client(tmp_path, deconstructor) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'deconstruction.db'}",
        upload_dir=tmp_path / "uploads",
    )
    return TestClient(
        create_app(
            settings,
            video_provider=FakeVideoUnderstanding(),
            case_deconstructor=deconstructor,
        )
    )


def analyzed_video(client: TestClient) -> str:
    _store_id, video_id = upload_asset(client)
    assert client.post(f"/api/v1/videos/{video_id}/analyze").status_code == 200
    return video_id


def test_deconstruct_returns_four_dimensions_and_caches(tmp_path) -> None:
    deconstructor = FakeDeconstructor()
    with build_client(tmp_path, deconstructor) as client:
        video_id = analyzed_video(client)

        first = client.post(f"/api/v1/videos/{video_id}/deconstruct")
        second = client.post(f"/api/v1/videos/{video_id}/deconstruct")

        assert first.status_code == 200
        body = first.json()
        assert body["is_fallback"] is False
        for dim in ("location", "product", "audience", "operation"):
            insight = body["result_json"][dim]
            assert insight["transfer"] == "adapt_required"
            assert insight["evidence"][0]["content"] == REAL_CLAIM
        assert second.json()["id"] == body["id"]
        assert deconstructor.call_count == 1


def test_fabricated_evidence_is_stripped_but_verdict_kept(tmp_path) -> None:
    with build_client(tmp_path, FakeDeconstructor("视频里根本没有这句话")) as client:
        video_id = analyzed_video(client)

        body = client.post(f"/api/v1/videos/{video_id}/deconstruct").json()

        for dim in ("location", "product", "audience", "operation"):
            insight = body["result_json"][dim]
            assert insight["evidence"] == []
            # 判断不因证据被剥而降级（§23 2026-07-22 决策）
            assert insight["transfer"] == "adapt_required"


def test_provider_failure_returns_honest_fallback(tmp_path) -> None:
    with build_client(tmp_path, FailingDeconstructor()) as client:
        video_id = analyzed_video(client)

        body = client.post(f"/api/v1/videos/{video_id}/deconstruct").json()

        assert body["is_fallback"] is True
        assert all(
            body["result_json"][dim]["transfer"] == "to_verify"
            for dim in ("location", "product", "audience", "operation")
        )


def test_deconstruct_requires_completed_analysis(tmp_path) -> None:
    with build_client(tmp_path, FakeDeconstructor()) as client:
        _store_id, video_id = upload_asset(client)

        response = client.post(f"/api/v1/videos/{video_id}/deconstruct")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "video_not_analyzed"


def test_same_content_same_category_reuses_deconstruction(tmp_path) -> None:
    provider = FakeDeconstructor()
    with build_client(tmp_path, provider) as client:
        video_id = analyzed_video(client)
        client.post(f"/api/v1/videos/{video_id}/deconstruct")

        # 同内容重新上传(演示案例重跑):同品类应复用解构,不再调模型
        user_id = client.post(
            "/api/v1/users",
            json={"display_name": "复用用户", "experience_level": "novice"},
        ).json()["id"]
        store_id = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={"name": "复用门店", "category": "奶茶", "stage": "planning"},
        ).json()["id"]
        second_video = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("advice.mp4", b"\x00\x00\x00\x18ftypmp42demo", "video/mp4")},
        ).json()["id"]
        assert client.post(f"/api/v1/videos/{second_video}/analyze").status_code == 200
        response = client.post(f"/api/v1/videos/{second_video}/deconstruct")

        assert response.status_code == 200
        assert response.json()["is_fallback"] is False
        assert provider.call_count == 1


def test_same_content_different_category_does_not_reuse(tmp_path) -> None:
    provider = FakeDeconstructor()
    with build_client(tmp_path, provider) as client:
        video_id = analyzed_video(client)
        client.post(f"/api/v1/videos/{video_id}/deconstruct")

        user_id = client.post(
            "/api/v1/users",
            json={"display_name": "咖啡用户", "experience_level": "novice"},
        ).json()["id"]
        store_id = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={"name": "咖啡门店", "category": "咖啡", "stage": "planning"},
        ).json()["id"]
        second_video = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("advice.mp4", b"\x00\x00\x00\x18ftypmp42demo", "video/mp4")},
        ).json()["id"]
        assert client.post(f"/api/v1/videos/{second_video}/analyze").status_code == 200
        client.post(f"/api/v1/videos/{second_video}/deconstruct")

        # 品类不同,迁移判断不可复用,必须重新生成
        assert provider.call_count == 2


