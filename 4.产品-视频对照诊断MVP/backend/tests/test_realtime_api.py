import httpx
from fastapi.testclient import TestClient

from yongge_online.core.config import Settings
from yongge_online.main import create_app


def create_store_and_session(client: TestClient) -> str:
    user_id = client.post(
        "/api/v1/users",
        json={"display_name": "实时用户", "experience_level": "novice"},
    ).json()["id"]
    store_id = client.post(
        f"/api/v1/users/{user_id}/stores",
        json={
            "name": "实时奶茶店",
            "category": "奶茶",
            "stage": "operating",
            "monthly_revenue": "30000",
            "monthly_rent": "10000",
            "monthly_labor_cost": "9000",
            "monthly_other_fixed_cost": "2000",
            "ingredient_cost_rate": "0.35",
        },
    ).json()["id"]
    return client.post(f"/api/v1/stores/{store_id}/sessions").json()["id"]


def test_realtime_config_contains_tools_but_never_permanent_key(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'realtime-config.db'}",
        upload_dir=tmp_path / "uploads",
        dashscope_api_key="never-return-this-key",
        dashscope_host="workspace.cn-beijing.maas.aliyuncs.com",
        qwen_realtime_model="qwen3.5-omni-flash-realtime",
    )
    with TestClient(create_app(settings)) as client:
        session_id = create_store_and_session(client)

        response = client.get(f"/api/v1/realtime/config/{session_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["model"] == "qwen3.5-omni-flash-realtime"
        assert body["session_update"]["type"] == "session.update"
        tool_names = {
            tool["function"]["name"]
            for tool in body["session_update"]["session"]["tools"]
        }
        assert tool_names == {
            "get_store_profile",
            "calculate",
            "calculate_business_metrics",
            "platform_rag",
            "retrieve_private_knowledge",
            "search_nearby_competitors",
        }
        assert all(
            tool["type"] == "function"
            for tool in body["session_update"]["session"]["tools"]
        )
        assert "实时奶茶店" in body["session_update"]["session"]["instructions"]
        assert "platform_rag" in body["session_update"]["session"]["instructions"]
        assert "never-return-this-key" not in response.text


def test_sdp_proxy_adds_server_side_authorization_and_returns_answer(tmp_path) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["content_type"] = request.headers["content-type"]
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, text="v=0\r\nanswer-sdp\r\n")

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'realtime-sdp.db'}",
        upload_dir=tmp_path / "uploads",
        dashscope_api_key="server-only-secret",
        dashscope_host="workspace.cn-beijing.maas.aliyuncs.com",
        qwen_realtime_model="qwen3.5-omni-flash-realtime",
    )
    app = create_app(settings, realtime_http_transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        session_id = create_store_and_session(client)

        response = client.post(
            f"/api/v1/realtime/sdp?session_id={session_id}",
            content="v=0\r\noffer-sdp\r\n",
            headers={"content-type": "application/sdp"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/sdp")
        assert response.text == "v=0\r\nanswer-sdp\r\n"
        assert captured == {
            "url": "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/webrtc/"
            "realtime?model=qwen3.5-omni-flash-realtime",
            "authorization": "Bearer server-only-secret",
            "content_type": "application/sdp",
            "body": "v=0\r\noffer-sdp\r\n",
        }


def test_realtime_instructions_include_case_context_and_camera_guidance(tmp_path) -> None:
    from tests.test_video_analysis import FakeVideoUnderstanding
    from tests.test_video_deconstruction import FakeDeconstructor

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'realtime-case.db'}",
        upload_dir=tmp_path / "uploads",
        dashscope_api_key="never-return-this-key",
        dashscope_host="workspace.cn-beijing.maas.aliyuncs.com",
    )
    app = create_app(
        settings,
        video_provider=FakeVideoUnderstanding(),
        case_deconstructor=FakeDeconstructor(),
    )
    with TestClient(app) as client:
        user_id = client.post(
            "/api/v1/users",
            json={"display_name": "案例用户", "experience_level": "novice"},
        ).json()["id"]
        store_id = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={"name": "想开奶茶店预算8万", "category": "奶茶", "stage": "planning"},
        ).json()["id"]
        video_id = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("case.mp4", b"\x00\x00\x00\x18ftypmp42demo", "video/mp4")},
        ).json()["id"]
        assert client.post(f"/api/v1/videos/{video_id}/analyze").status_code == 200
        assert client.post(f"/api/v1/videos/{video_id}/deconstruct").status_code == 200
        session_id = client.post(f"/api/v1/stores/{store_id}/sessions").json()["id"]

        instructions = client.get(f"/api/v1/realtime/config/{session_id}").json()[
            "session_update"
        ]["session"]["instructions"]

        # 案例上下文注入:解析摘要 + 四维初判(FakeDeconstructor 全维 adapt_required)
        assert "视频指出门店收入不足" in instructions
        assert "需要改" in instructions
        # 用户已知信息注入,专家不重复问
        assert "想开奶茶店预算8万" in instructions
        # 镜头引导按证据缺口触发，不用固定次数完成任务。
        assert "镜头引导" in instructions
        assert "门头" in instructions
        assert "缓慢绕一圈" in instructions
        assert "不规定次数" in instructions
        assert "每次发言最多 3 句话" in instructions
        assert "至少两次" not in instructions
        assert "确定性数字" in instructions
        assert "calculate" in instructions


def test_realtime_instructions_survive_missing_case(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'realtime-nocase.db'}",
        upload_dir=tmp_path / "uploads",
        dashscope_api_key="never-return-this-key",
        dashscope_host="workspace.cn-beijing.maas.aliyuncs.com",
    )
    with TestClient(create_app(settings)) as client:
        session_id = create_store_and_session(client)

        response = client.get(f"/api/v1/realtime/config/{session_id}")

        assert response.status_code == 200
        instructions = response.json()["session_update"]["session"]["instructions"]
        assert "解析可能还在后台进行" in instructions
        assert "镜头引导" in instructions


def test_realtime_voice_defaults_to_male_and_honors_cloned_voice(tmp_path) -> None:
    # 未配置复刻音色 → 男声预置音色兜底(口袋哥是男生,不能落回默认女声)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'voice-default.db'}",
        upload_dir=tmp_path / "uploads",
        dashscope_api_key="never-return-this-key",
        dashscope_host="workspace.cn-beijing.maas.aliyuncs.com",
        qwen_realtime_voice=None,  # 隔离本机 .env,验证兜底逻辑
        qwen_realtime_fallback_voice="Ethan",
    )
    with TestClient(create_app(settings)) as client:
        session_id = create_store_and_session(client)
        body = client.get(f"/api/v1/realtime/config/{session_id}").json()
        assert body["session_update"]["session"]["voice"] == "Ethan"

    settings2 = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'voice-cloned.db'}",
        upload_dir=tmp_path / "uploads",
        dashscope_api_key="never-return-this-key",
        dashscope_host="workspace.cn-beijing.maas.aliyuncs.com",
        qwen_realtime_voice="qwen-omni-vc-demo-voice",
    )
    with TestClient(create_app(settings2)) as client:
        session_id = create_store_and_session(client)
        body = client.get(f"/api/v1/realtime/config/{session_id}").json()
        assert body["session_update"]["session"]["voice"] == "qwen-omni-vc-demo-voice"


