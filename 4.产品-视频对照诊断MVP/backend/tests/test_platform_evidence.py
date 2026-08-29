import asyncio

from fastapi.testclient import TestClient

from yongge_online.core.config import Settings
from yongge_online.db.session import Database
from yongge_online.diagnosis.schemas import (
    DiagnosisConclusion,
    DiagnosisReport,
    EvidenceRef,
    ProblemFinding,
)
from yongge_online.knowledge.platform import PlatformKnowledgeService
from yongge_online.knowledge.schemas import PlatformKnowledgeUpsert
from yongge_online.main import create_app


class PlatformEvidenceReportGenerator:
    async def generate_report(self, *, context: dict) -> DiagnosisReport:
        platform_id = context["tool_calls"][0]["result"]["evidence_ids"][0]
        return DiagnosisReport(
            summary="该案例的选址做法需要结合用户现场条件迁移。",
            conclusion=DiagnosisConclusion.OBSERVE,
            confidence=0.72,
            problems=[
                ProblemFinding(
                    title="需要核验目标时段门头可见性",
                    priority="P0",
                    category="location",
                    rationale="平台审核规则要求先验证现场证据。",
                    evidence_refs=[
                        EvidenceRef(
                            source_type="knowledge_item",
                            source_id=platform_id,
                            description="平台专家选址规则",
                        )
                    ],
                )
            ],
        )


async def seed_platform_knowledge(database_url: str) -> None:
    database = Database(database_url)
    await database.create_schema()
    try:
        async with database.session() as session:
            await PlatformKnowledgeService(session).upsert_many(
                [
                    PlatformKnowledgeUpsert(
                        id="platform-rule-evidence-1",
                        source_type="expert_video",
                        source_id="video-evidence-1",
                        kind="rule",
                        content="选址前要在目标时段核验门头可见性。",
                        tags=["选址", "门头"],
                        applicable_categories=["奶茶"],
                        business_stages=["planning"],
                        review_status="reviewed",
                    )
                ]
            )
            await session.commit()
    finally:
        await database.dispose()


def test_report_accepts_platform_rag_hit_as_knowledge_evidence(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'platform-evidence.db'}"
    asyncio.run(seed_platform_knowledge(database_url))
    settings = Settings(database_url=database_url, upload_dir=tmp_path / "uploads")
    app = create_app(settings, report_provider=PlatformEvidenceReportGenerator())

    with TestClient(app) as client:
        user_id = client.post(
            "/api/v1/users",
            json={"display_name": "案例迁移用户", "experience_level": "novice"},
        ).json()["id"]
        store_id = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={
                "name": "筹备中的奶茶店",
                "category": "奶茶",
                "stage": "planning",
            },
        ).json()["id"]
        session_id = client.post(f"/api/v1/stores/{store_id}/sessions").json()["id"]

        tool = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "platform-rag-call-1",
                "tool_name": "platform_rag",
                "arguments": {"query": "选址门头", "category": "奶茶"},
            },
        )
        assert tool.status_code == 200
        assert tool.json()["result"]["evidence_ids"] == ["platform-rule-evidence-1"]

        completion = client.post(f"/api/v1/sessions/{session_id}/complete")

        assert completion.status_code == 200
        assert completion.json()["is_fallback"] is False
        reference = completion.json()["report"]["problems"][0]["evidence_refs"][0]
        assert reference == {
            "source_type": "knowledge_item",
            "source_id": "platform-rule-evidence-1",
            "description": "平台专家选址规则",
        }


