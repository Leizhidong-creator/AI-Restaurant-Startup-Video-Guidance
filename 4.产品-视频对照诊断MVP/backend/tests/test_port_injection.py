from fastapi.testclient import TestClient

from yongge_online.core.config import Settings
from yongge_online.main import create_app
from yongge_online.skills.ports import SkillContext


class InjectedPrivateRetriever:
    async def search(self, *, user_id: str, store_id: str, query: str, limit: int):
        return [
            {
                "id": "private-injected-1",
                "kind": "case",
                "content": "用户确认过的私人案例",
                "tags": ["私人"],
                "start_ms": None,
                "end_ms": None,
                "score": 1.0,
            }
        ]


class InjectedPlatformRetriever:
    async def search(self, **_kwargs):
        return [
            {
                "id": "platform-injected-1",
                "scope": "platform",
                "source_type": "expert_video",
                "source_id": "video-injected-1",
                "kind": "rule",
                "content": "平台审核过的选址规则",
                "tags": ["选址"],
                "start_ms": 1000,
                "end_ms": 5000,
                "score": 0.9,
                "review_status": "reviewed",
            }
        ]


class StatefulSkillEngine:
    def __init__(self) -> None:
        self.contexts = []

    async def build_session_instructions(self, context: SkillContext) -> str:
        return f"为 {context.store.name} 执行逐轮餐饮决策。"

    async def advance(self, context):
        self.contexts.append(context)
        return {
            "directive": {
                "action": "ask",
                "message": "请先告诉我你能承受的最高月租。",
                "missing_facts": ["monthly_rent_budget"],
                "question_candidates": [],
                "tool_name": None,
                "tool_arguments": {},
                "allowed_conclusions": [],
                "warning": None,
                "unavailable_tools": ["current_business_lookup"],
                "rationale_codes": ["missing_financial_boundary"],
            },
            "tool_results": {},
            "trace": [],
        }


def create_store_and_session(client: TestClient) -> tuple[str, str]:
    user_id = client.post(
        "/api/v1/users",
        json={"display_name": "端口测试用户", "experience_level": "novice"},
    ).json()["id"]
    store_id = client.post(
        f"/api/v1/users/{user_id}/stores",
        json={"name": "端口测试店", "category": "奶茶", "stage": "planning"},
    ).json()["id"]
    session_id = client.post(f"/api/v1/stores/{store_id}/sessions").json()["id"]
    return store_id, session_id


def test_create_app_injects_private_and_platform_retriever_ports(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'retriever-ports.db'}",
        upload_dir=tmp_path / "uploads",
    )
    private = InjectedPrivateRetriever()
    platform = InjectedPlatformRetriever()
    app = create_app(
        settings,
        private_retriever_factory=lambda _session: private,
        platform_retriever_factory=lambda _session: platform,
    )

    with TestClient(app) as client:
        _store_id, session_id = create_store_and_session(client)
        private_result = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "private-port-1",
                "tool_name": "retrieve_private_knowledge",
                "arguments": {"query": "私人案例"},
            },
        )
        platform_result = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "platform-port-1",
                "tool_name": "platform_rag",
                "arguments": {"query": "选址规则"},
            },
        )

        assert private_result.json()["result"]["hits"][0]["id"] == "private-injected-1"
        assert platform_result.json()["result"]["evidence_ids"] == [
            "platform-injected-1"
        ]


def test_skill_engine_advance_receives_and_persists_session_context(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'skill-port.db'}",
        upload_dir=tmp_path / "uploads",
    )
    skill = StatefulSkillEngine()
    app = create_app(settings, skill_engine=skill)

    with TestClient(app) as client:
        store_id, session_id = create_store_and_session(client)
        client.post(
            f"/api/v1/sessions/{session_id}/events",
            json={
                "event_type": "user_fact",
                "actor": "user",
                "payload": {"city": "武汉"},
            },
        )

        first = client.post(
            f"/api/v1/sessions/{session_id}/skill/advance",
            json={
                "facts": {"city": "武汉"},
                "evidence": {},
                "hypotheses": [],
                "has_private_knowledge": False,
            },
        )

        assert first.status_code == 200
        assert first.json()["directive"]["action"] == "ask"
        assert first.json()["directive"]["missing_facts"] == ["monthly_rent_budget"]
        assert first.json()["directive"]["unavailable_tools"] == [
            "current_business_lookup"
        ]
        assert first.json()["directive"]["rationale_codes"] == [
            "missing_financial_boundary"
        ]
        context = skill.contexts[0]
        assert context.session_id == session_id
        assert context.store.id == store_id
        assert context.facts == {"city": "武汉"}
        assert context.events[0]["event_type"] == "user_fact"

        second = client.post(
            f"/api/v1/sessions/{session_id}/skill/advance",
            json={"facts": {"city": "武汉"}},
        )
        assert second.status_code == 200
        assert any(
            event["event_type"] == "skill_directive" for event in skill.contexts[1].events
        )


