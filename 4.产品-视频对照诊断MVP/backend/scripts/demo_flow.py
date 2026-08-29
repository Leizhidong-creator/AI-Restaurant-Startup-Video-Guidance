"""Drive the complete Task 3 HTTP workflow against a running API server."""

import argparse
import mimetypes
from pathlib import Path

import httpx


def require_success(response: httpx.Response) -> dict:
    if not response.is_success:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def run(base_url: str, video_path: Path) -> None:
    if not video_path.is_file():
        raise SystemExit(f"Video does not exist: {video_path}")
    content_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"

    with httpx.Client(base_url=base_url, timeout=300) as client:
        user = require_success(
            client.post(
                "/api/v1/users",
                json={"display_name": "演示店主", "experience_level": "novice"},
            )
        )
        store = require_success(
            client.post(
                f"/api/v1/users/{user['id']}/stores",
                json={
                    "name": "武汉演示奶茶店",
                    "category": "奶茶",
                    "stage": "operating",
                    "address": "武汉市洪山区",
                    "monthly_revenue": "36000",
                    "monthly_rent": "12000",
                    "monthly_labor_cost": "11000",
                    "monthly_other_fixed_cost": "3000",
                    "ingredient_cost_rate": "0.35",
                    "operating_days_per_month": 30,
                },
            )
        )
        with video_path.open("rb") as file_handle:
            video = require_success(
                client.post(
                    f"/api/v1/stores/{store['id']}/videos",
                    files={"file": (video_path.name, file_handle, content_type)},
                )
            )
        video = require_success(client.post(f"/api/v1/videos/{video['id']}/analyze"))
        knowledge = require_success(
            client.post(
                f"/api/v1/stores/{store['id']}/knowledge/search",
                json={"query": "经营风险 保本营业额", "limit": 5},
            )
        )
        session = require_success(client.post(f"/api/v1/stores/{store['id']}/sessions"))
        require_success(
            client.post(
                f"/api/v1/sessions/{session['id']}/events",
                json={
                    "event_type": "transcript",
                    "actor": "user",
                    "payload": {"text": "这家店最近每天营业额大约 1200 元"},
                },
            )
        )
        for call_id, tool_name, arguments in (
            ("demo-metrics", "calculate_business_metrics", {}),
            (
                "demo-knowledge",
                "retrieve_private_knowledge",
                {"query": "经营风险 保本营业额", "limit": 5},
            ),
            ("demo-map", "search_nearby_competitors", {"radius_m": 1000}),
        ):
            require_success(
                client.post(
                    f"/api/v1/sessions/{session['id']}/tools/execute",
                    json={
                        "call_id": call_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                    },
                )
            )
        report = require_success(client.post(f"/api/v1/sessions/{session['id']}/complete"))

    print(f"User: {user['id']}")
    print(f"Store: {store['id']}")
    print(f"Video: {video['id']} ({video['status']})")
    print(f"Knowledge hits: {len(knowledge['hits'])}")
    print(f"Session: {session['id']}")
    print(f"Conclusion: {report['report']['conclusion']}")
    print(f"Summary: {report['report']['summary']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--video", type=Path, required=True)
    args = parser.parse_args()
    run(args.base_url, args.video)


if __name__ == "__main__":
    main()


