from fastapi.testclient import TestClient

from tests.test_video_analysis import FakeVideoUnderstanding
from yongge_online.core.config import Settings
from yongge_online.diagnosis.schemas import (
    ActionItem,
    DiagnosisConclusion,
    DiagnosisReport,
    EvidenceRef,
    ProblemFinding,
)
from yongge_online.main import create_app


class FakeReportGenerator:
    async def generate_report(self, *, context: dict) -> DiagnosisReport:
        tool_call_id = context["tool_calls"][0]["id"]
        knowledge_id = context["knowledge"][0]["id"]
        return DiagnosisReport(
            summary="门店当前收入低于保本线，应先执行七天数据整改。",
            conclusion=DiagnosisConclusion.RECTIFY,
            confidence=0.86,
            problems=[
                ProblemFinding(
                    title="营业额未达到保本线",
                    priority="P0",
                    category="revenue",
                    rationale="确定性计算显示月营业额低于保本营业额。",
                    evidence_refs=[
                        EvidenceRef(
                            source_type="tool_call",
                            source_id=tool_call_id,
                            description="盈亏和保本点计算",
                        ),
                        EvidenceRef(
                            source_type="knowledge_item",
                            source_id=knowledge_id,
                            description="上传视频中的保本点方法",
                        ),
                    ],
                )
            ],
            immediate_actions=[
                ActionItem(
                    title="开始七天经营数据记录",
                    timeframe="今天开始",
                    steps=["记录订单数", "记录营业额", "记录客单价"],
                    success_metric="七天数据完整率 100%",
                )
            ],
            short_term_actions=[],
            observation_metrics=["每日营业额", "订单数", "客单价"],
            information_gaps=["缺少高德周边竞品数据"],
        )


def build_client(tmp_path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'diagnosis.db'}",
        upload_dir=tmp_path / "uploads",
    )
    return TestClient(
        create_app(
            settings,
            video_provider=FakeVideoUnderstanding(),
            report_provider=FakeReportGenerator(),
        )
    )


def seed_store_and_knowledge(client: TestClient) -> tuple[str, str]:
    user_id = client.post(
        "/api/v1/users",
        json={"display_name": "诊断用户", "experience_level": "novice"},
    ).json()["id"]
    store_id = client.post(
        f"/api/v1/users/{user_id}/stores",
        json={
            "name": "亏损奶茶店",
            "category": "奶茶",
            "stage": "operating",
            "monthly_revenue": "36000",
            "monthly_rent": "12000",
            "monthly_labor_cost": "11000",
            "monthly_other_fixed_cost": "3000",
            "ingredient_cost_rate": "0.35",
            "operating_days_per_month": 30,
        },
    ).json()["id"]
    video_id = client.post(
        f"/api/v1/stores/{store_id}/videos",
        files={"file": ("advice.mp4", b"\x00\x00\x00\x18ftypmp42demo", "video/mp4")},
    ).json()["id"]
    assert client.post(f"/api/v1/videos/{video_id}/analyze").status_code == 200
    return user_id, store_id


def test_complete_diagnosis_persists_events_tools_and_evidence_report(tmp_path) -> None:
    with build_client(tmp_path) as client:
        _user_id, store_id = seed_store_and_knowledge(client)

        session_response = client.post(f"/api/v1/stores/{store_id}/sessions")
        assert session_response.status_code == 201
        session_id = session_response.json()["id"]

        event_response = client.post(
            f"/api/v1/sessions/{session_id}/events",
            json={
                "event_type": "transcript",
                "actor": "user",
                "payload": {"text": "最近每天营业额大约 1200 元"},
            },
        )
        assert event_response.status_code == 201
        assert event_response.json()["sequence"] == 1

        first_tool = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "call-metrics-1",
                "tool_name": "calculate_business_metrics",
                "arguments": {},
            },
        )
        assert first_tool.status_code == 200
        assert first_tool.json()["result"]["monthly_profit"] == "-2600.00"

        repeated_tool = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "call-metrics-1",
                "tool_name": "calculate_business_metrics",
                "arguments": {},
            },
        )
        assert repeated_tool.json()["id"] == first_tool.json()["id"]

        completion = client.post(f"/api/v1/sessions/{session_id}/complete")

        assert completion.status_code == 200
        report = completion.json()
        assert report["is_fallback"] is False
        assert report["report"]["conclusion"] == "rectify"
        references = report["report"]["problems"][0]["evidence_refs"]
        assert {ref["source_type"] for ref in references} == {
            "tool_call",
            "knowledge_item",
        }

        get_report = client.get(f"/api/v1/sessions/{session_id}/report")
        assert get_report.status_code == 200
        assert get_report.json()["id"] == report["id"]


class FabricatingReportGenerator:
    """模拟模型抄错/编造证据 id:一个问题真假引用混合,一个问题全是假引用。"""

    async def generate_report(self, *, context: dict) -> DiagnosisReport:
        real_event_id = context["events"][0]["id"]
        mixed = ProblemFinding(
            title="真假证据混合的问题",
            priority="P1",
            category="revenue",
            rationale="其中一条引用是编造的。",
            evidence_refs=[
                EvidenceRef(
                    source_type="session_event",
                    source_id=real_event_id,
                    description="真实事件",
                ),
                EvidenceRef(
                    source_type="session_event",
                    source_id="00000000-0000-0000-0000-000000000000",
                    description="编造事件",
                ),
            ],
        )
        fabricated_only = ProblemFinding(
            title="证据全编造的问题",
            priority="P2",
            category="other",
            rationale="引用完全不存在。",
            evidence_refs=[
                EvidenceRef(
                    source_type="tool_call",
                    source_id="not-a-real-tool-call",
                    description="编造工具调用",
                )
            ],
        )
        return DiagnosisReport(
            summary="用于验证校准式护栏的报告。",
            conclusion=DiagnosisConclusion.OBSERVE,
            confidence=0.6,
            problems=[mixed, fabricated_only],
            immediate_actions=[],
            short_term_actions=[],
            observation_metrics=[],
            information_gaps=[],
        )


def test_fabricated_evidence_is_stripped_not_downgraded(tmp_path) -> None:
    """校准式护栏(PRD §23 2026-07-22):剥假证据、留判断,不整报告降级。"""
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'strip.db'}",
        upload_dir=tmp_path / "uploads",
    )
    app = create_app(
        settings,
        video_provider=FakeVideoUnderstanding(),
        report_provider=FabricatingReportGenerator(),
    )
    with TestClient(app) as client:
        _user_id, store_id = seed_store_and_knowledge(client)
        session_id = client.post(f"/api/v1/stores/{store_id}/sessions").json()["id"]
        assert (
            client.post(
                f"/api/v1/sessions/{session_id}/events",
                json={
                    "event_type": "transcript",
                    "actor": "user",
                    "payload": {"text": "现场信息"},
                },
            ).status_code
            == 201
        )

        completion = client.post(f"/api/v1/sessions/{session_id}/complete")

        assert completion.status_code == 200
        body = completion.json()
        assert body["is_fallback"] is False  # 不降级
        report = body["report"]
        assert report["conclusion"] == "observe"  # 判断保留
        assert len(report["problems"]) == 1  # 全假证据的问题被丢弃
        refs = report["problems"][0]["evidence_refs"]
        assert len(refs) == 1  # 混合问题里的假引用被剥掉
        assert refs[0]["source_id"] != "00000000-0000-0000-0000-000000000000"
        gaps = " ".join(report["information_gaps"])
        assert "剥除" in gaps and "丢弃" in gaps  # 透明记录


def test_sessions_and_events_are_listable_for_review(tmp_path) -> None:
    # 回看页(web/review.html)依赖:最近会话列表 + 单会话事件时间线
    from fastapi.testclient import TestClient

    from yongge_online.core.config import Settings
    from yongge_online.main import create_app

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'review.db'}",
        upload_dir=tmp_path / "uploads",
    )
    with TestClient(create_app(settings)) as client:
        user_id = client.post(
            "/api/v1/users",
            json={"display_name": "回看用户", "experience_level": "novice"},
        ).json()["id"]
        store_id = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={"name": "回看门店", "category": "奶茶", "stage": "planning"},
        ).json()["id"]
        session_id = client.post(f"/api/v1/stores/{store_id}/sessions").json()["id"]
        client.post(
            f"/api/v1/sessions/{session_id}/events",
            json={"actor": "assistant", "event_type": "transcript", "payload": {"text": "你好"}},
        )

        sessions = client.get("/api/v1/sessions?limit=5").json()
        assert sessions[0]["id"] == session_id

        events = client.get(f"/api/v1/sessions/{session_id}/events").json()
        assert [e["event_type"] for e in events] == ["transcript"]
        assert events[0]["payload"]["text"] == "你好"


