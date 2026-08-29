from tests.test_diagnosis_flow import build_client, seed_store_and_knowledge


def test_http_workflow_runs_from_profile_to_report_with_map_degradation(tmp_path) -> None:
    with build_client(tmp_path) as client:
        _user_id, store_id = seed_store_and_knowledge(client)
        session_id = client.post(f"/api/v1/stores/{store_id}/sessions").json()["id"]

        assert client.post(
            f"/api/v1/sessions/{session_id}/events",
            json={
                "event_type": "transcript",
                "actor": "user",
                "payload": {"text": "请帮我判断这家店应该整改还是止损"},
            },
        ).status_code == 201

        calculation = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "e2e-calc",
                "tool_name": "calculate_business_metrics",
                "arguments": {},
            },
        ).json()["result"]
        assert calculation["available"] is True
        assert calculation["monthly_profit"] == "-2600.00"

        retrieval = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "e2e-knowledge",
                "tool_name": "retrieve_private_knowledge",
                "arguments": {"query": "保本营业额", "limit": 3},
            },
        ).json()["result"]
        assert retrieval["hits"]

        map_result = client.post(
            f"/api/v1/sessions/{session_id}/tools/execute",
            json={
                "call_id": "e2e-map",
                "tool_name": "search_nearby_competitors",
                "arguments": {"radius_m": 1000},
            },
        ).json()["result"]
        assert map_result["available"] is False
        assert "经纬度" in map_result["reason"]

        report = client.post(f"/api/v1/sessions/{session_id}/complete").json()
        assert report["report"]["conclusion"] == "rectify"
        assert report["report"]["problems"]


def test_development_app_accepts_frontend_cors_preflight(tmp_path) -> None:
    with build_client(tmp_path) as client:
        response = client.options(
            "/health",
            headers={
                "origin": "http://localhost:5173",
                "access-control-request-method": "GET",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


