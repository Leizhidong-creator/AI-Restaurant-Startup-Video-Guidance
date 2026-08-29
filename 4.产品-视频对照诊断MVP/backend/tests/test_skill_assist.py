"""服务端确定性辅助(assist)与报告结论阶段门的测试。

背景(PRD §23 2026-07-23):实测 12 场真实会话模型自主 function call 为 0 次,
故工具纪律改由服务端在 /skill/advance 里机械触发;报告结论词表按门店阶段硬校验。
"""

from decimal import Decimal

from fastapi.testclient import TestClient

from yongge_online.core.config import Settings
from yongge_online.diagnosis.schemas import DiagnosisConclusion, DiagnosisReport
from yongge_online.main import create_app
from yongge_online.skills.assist import (
    compose_assist_message,
    extract_metric_updates,
    should_query_kb,
)


# ---------- 纯函数:标签+数字提取 ----------


def test_extract_labeled_amounts() -> None:
    updates = extract_metric_updates("租金1万2,营业额3万5,水电3000")
    assert updates["monthly_rent"] == "12000"
    assert updates["monthly_revenue"] == "35000"
    assert updates["monthly_other_fixed_cost"] == "3000"


def test_extract_supports_filler_and_qian() -> None:
    updates = extract_metric_updates("房租每个月大概8千,人工是11000")
    assert updates["monthly_rent"] == "8000"
    assert updates["monthly_labor_cost"] == "11000"


def test_extract_cost_rate_percent() -> None:
    assert extract_metric_updates("食材成本率35%")["ingredient_cost_rate"] == "0.35"


def test_extract_ignores_unlabeled_and_chinese_numerals() -> None:
    # 无标签数字不猜字段;中文数字(两万)不解析——漏掉是诚实的
    assert extract_metric_updates("大概两万吧,还有 8000 说不清是什么") == {}


def test_extract_wan_tail_must_be_adjacent() -> None:
    # "1万 2个人" 的 2 属于人数,不能读成 1.2 万
    assert extract_metric_updates("租金1万 2个人")["monthly_rent"] == "10000"


def test_kb_gate_blocks_chitchat() -> None:
    assert not should_query_kb("有看到我的画面吗")
    assert should_query_kb("加盟一家奶茶店大概要多少预算")


def test_compose_empty_when_nothing() -> None:
    assert compose_assist_message({}, None, None) == ""


# ---------- 集成:/skill/advance 服务端辅助 ----------


def _build_client(tmp_path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'assist.db'}",
        upload_dir=tmp_path / "uploads",
    )
    return TestClient(create_app(settings))


def _seed_session(client: TestClient, *, stage: str) -> str:
    user_id = client.post(
        "/api/v1/users",
        json={"display_name": "辅助测试", "experience_level": "novice"},
    ).json()["id"]
    store_id = client.post(
        f"/api/v1/users/{user_id}/stores",
        json={"name": "测试店", "category": "奶茶", "stage": stage},
    ).json()["id"]
    response = client.post(f"/api/v1/stores/{store_id}/sessions")
    assert response.status_code == 201
    return response.json()["id"]


def test_advance_with_numbers_runs_calculation_and_logs_tool_call(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        session_id = _seed_session(client, stage="planning")
        response = client.post(
            f"/api/v1/sessions/{session_id}/skill/advance",
            json={"facts": {"latest_user_utterance": "租金1万2,人工8000,水电2000"}},
        )
        assert response.status_code == 200
        body = response.json()
        message = body["directive"]["message"]
        assert message.startswith("【后台通知】")
        assert "12000" in message  # 复述了用户给的数
        assert "calculate_business_metrics" in body["tool_results"]
        # 工具执行必须落 tool_calls 表(经 execute_tool),事件必须落 skill_directive
        events = client.get(f"/api/v1/sessions/{session_id}/events").json()
        assert any(e["event_type"] == "skill_directive" for e in events)


def test_advance_chitchat_is_noop_and_not_logged(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        session_id = _seed_session(client, stage="planning")
        response = client.post(
            f"/api/v1/sessions/{session_id}/skill/advance",
            json={"facts": {"latest_user_utterance": "有看到我的画面吗"}},
        )
        assert response.status_code == 200
        assert response.json()["directive"]["message"] == ""
        events = client.get(f"/api/v1/sessions/{session_id}/events").json()
        assert not any(e["event_type"] == "skill_directive" for e in events)


# ---------- 报告结论阶段门 ----------


class _FixedConclusionGenerator:
    def __init__(self, conclusion: DiagnosisConclusion):
        self.conclusion = conclusion

    async def generate_report(self, *, context: dict) -> DiagnosisReport:
        return DiagnosisReport(
            summary="测试结论。",
            conclusion=self.conclusion,
            confidence=0.9,
        )


def _client_with_generator(tmp_path, conclusion: DiagnosisConclusion) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'gate.db'}",
        upload_dir=tmp_path / "uploads",
    )
    return TestClient(
        create_app(settings, report_provider=_FixedConclusionGenerator(conclusion))
    )


def test_stage_gate_remaps_stop_loss_for_planning_store(tmp_path) -> None:
    with _client_with_generator(tmp_path, DiagnosisConclusion.STOP_LOSS) as client:
        session_id = _seed_session(client, stage="planning")
        report = client.post(f"/api/v1/sessions/{session_id}/complete").json()
        assert report["report"]["conclusion"] == "do_not_proceed"
        assert any("越权" in gap for gap in report["report"]["information_gaps"])


def test_stage_gate_keeps_stop_loss_for_operating_store(tmp_path) -> None:
    with _client_with_generator(tmp_path, DiagnosisConclusion.STOP_LOSS) as client:
        session_id = _seed_session(client, stage="operating")
        report = client.post(f"/api/v1/sessions/{session_id}/complete").json()
        assert report["report"]["conclusion"] == "stop_loss"
        assert not any("越权" in gap for gap in report["report"]["information_gaps"])


def test_stage_gate_remaps_proceed_for_operating_store(tmp_path) -> None:
    with _client_with_generator(tmp_path, DiagnosisConclusion.PROCEED) as client:
        session_id = _seed_session(client, stage="operating")
        report = client.post(f"/api/v1/sessions/{session_id}/complete").json()
        assert report["report"]["conclusion"] == "observe"


