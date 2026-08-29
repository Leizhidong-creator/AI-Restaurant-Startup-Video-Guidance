
from tests.test_video_analysis import (
    FakeVideoUnderstanding,
    build_client,
    upload_asset,
)


def test_keyword_retriever_returns_scored_private_hits(tmp_path) -> None:
    with build_client(tmp_path, FakeVideoUnderstanding()) as client:
        store_id, video_id = upload_asset(client)
        assert client.post(f"/api/v1/videos/{video_id}/analyze").status_code == 200

        response = client.post(
            f"/api/v1/stores/{store_id}/knowledge/search",
            json={"query": "保本营业额", "limit": 3},
        )

        assert response.status_code == 200
        hits = response.json()["hits"]
        assert hits
        assert hits[0]["kind"] == "claim"
        assert hits[0]["score"] > 0
        assert "保本营业额" in hits[0]["content"]


