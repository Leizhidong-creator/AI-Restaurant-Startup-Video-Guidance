import hashlib

import pytest
from fastapi.testclient import TestClient

from yongge_online.core.config import Settings
from yongge_online.main import create_app


def build_client(
    tmp_path, *, max_upload_mb: int = 1, video_link_relevance_checker=None
) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'videos.db'}",
        upload_dir=tmp_path / "uploads",
        max_upload_mb=max_upload_mb,
    )
    return TestClient(
        create_app(
            settings,
            video_link_relevance_checker=video_link_relevance_checker,
        )
    )


def create_store(client: TestClient) -> str:
    user_id = client.post(
        "/api/v1/users",
        json={"display_name": "视频测试用户", "experience_level": "novice"},
    ).json()["id"]
    return client.post(
        f"/api/v1/users/{user_id}/stores",
        json={"name": "测试奶茶店", "category": "奶茶", "stage": "operating"},
    ).json()["id"]


def test_upload_video_uses_safe_storage_name_and_records_hash(tmp_path) -> None:
    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"business-video"
    with build_client(tmp_path) as client:
        store_id = create_store(client)

        response = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("餐饮专家经验.mp4", video_bytes, "video/mp4")},
        )

        assert response.status_code == 201
        asset = response.json()
        assert asset["store_id"] == store_id
        assert asset["filename"] == "餐饮专家经验.mp4"
        assert asset["status"] == "uploaded"
        assert asset["sha256"] == hashlib.sha256(video_bytes).hexdigest()
        assert "餐饮专家经验" not in asset["storage_uri"]

        saved_path = tmp_path / asset["storage_uri"]
        assert saved_path.read_bytes() == video_bytes

        get_response = client.get(f"/api/v1/videos/{asset['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["size_bytes"] == len(video_bytes)


def test_upload_rejects_non_video_extension(tmp_path) -> None:
    with build_client(tmp_path) as client:
        store_id = create_store(client)

        response = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_video"


def test_upload_rejects_file_over_configured_limit(tmp_path) -> None:
    with build_client(tmp_path, max_upload_mb=1) as client:
        store_id = create_store(client)

        response = client.post(
            f"/api/v1/stores/{store_id}/videos",
            files={"file": ("huge.mp4", b"x" * (1024 * 1024 + 1), "video/mp4")},
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "video_too_large"


def test_ingest_url_reuses_upload_pipeline(tmp_path, monkeypatch) -> None:
    from yongge_online.videos import link_source
    from yongge_online.videos.link_source import FetchedVideo

    def fake_fetch(text, *, max_bytes):
        assert "v.douyin.com" in text
        return FetchedVideo(
            filename="爆火小吃店.mp4",
            content_type="video/mp4",
            content=b"\x00\x00\x00\x18ftypmp42link",
            title="爆火小吃店",
        )

    monkeypatch.setattr(link_source, "fetch_video_from_url", fake_fetch)
    with build_client(tmp_path) as client:
        store_id = create_store(client)
        response = client.post(
            f"/api/v1/stores/{store_id}/videos/from-url",
            json={"url": "看看这家店 https://v.douyin.com/abc123/ 复制此链接"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["filename"] == "爆火小吃店.mp4"
        assert body["status"] == "uploaded"

        status_response = client.get("/api/v1/system/video-source-status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "healthy"
        assert status_response.json()["resolutions_24h"] == 1


def test_fallback_event_exposes_cookie_degradation(tmp_path, monkeypatch) -> None:
    from yongge_online.videos import link_source
    from yongge_online.videos.link_source import FetchedVideo

    monkeypatch.setenv("YT_DLP_COOKIES_FILE", "/run/secrets/douyin-cookies.txt")
    monkeypatch.setattr(
        link_source,
        "fetch_video_from_url",
        lambda text, *, max_bytes: FetchedVideo(
            filename="兜底视频.mp4",
            content_type="video/mp4",
            content=b"\x00\x00\x00\x18ftypmp42fallback",
            title="兜底视频",
            source_provider="miuistore",
            primary_failure_reason="cookie_invalid_or_expired",
        ),
    )

    with build_client(tmp_path) as client:
        store_id = create_store(client)
        response = client.post(
            f"/api/v1/stores/{store_id}/videos/from-url",
            json={"url": "https://v.douyin.com/fallback/"},
        )
        assert response.status_code == 201

        status_body = client.get("/api/v1/system/video-source-status").json()
        assert status_body["status"] == "degraded_cookie"
        assert status_body["cookie_file_configured"] is True
        assert status_body["last_selected_provider"] == "miuistore"
        assert status_body["last_primary_failure_reason"] == "cookie_invalid_or_expired"
        assert status_body["fallbacks_24h"] == 1
        assert status_body["cookie_failures_24h"] == 1


def test_ingest_url_rejects_unresolvable(tmp_path, monkeypatch) -> None:
    from yongge_online.core.errors import DomainError
    from yongge_online.videos import link_source

    def fail_fetch(text, *, max_bytes):
        raise DomainError("链接解析失败", code="video_url_unresolvable", status_code=422)

    monkeypatch.setattr(link_source, "fetch_video_from_url", fail_fetch)
    with build_client(tmp_path) as client:
        store_id = create_store(client)
        response = client.post(
            f"/api/v1/stores/{store_id}/videos/from-url",
            json={"url": "https://v.douyin.com/gone/"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "video_url_unresolvable"


def test_preview_url_flags_low_relevance_without_downloading(tmp_path, monkeypatch) -> None:
    from yongge_online.videos import link_source
    from yongge_online.videos.link_source import VideoLinkMetadata
    from yongge_online.videos.schemas import (
        VideoLinkRelevance,
        VideoLinkRelevanceResult,
    )

    class LowRelevanceChecker:
        async def check_link_metadata(self, *, title, description):
            assert title == "王者荣耀五杀集锦"
            assert description == "本周排位精彩操作"
            return VideoLinkRelevanceResult(
                relevance=VideoLinkRelevance.LOW,
                reason="内容是游戏集锦，与餐饮经营无明显关系",
            )

    monkeypatch.setattr(
        link_source,
        "preview_video_url",
        lambda text: VideoLinkMetadata(
            title="王者荣耀五杀集锦",
            description="本周排位精彩操作",
        ),
    )
    monkeypatch.setattr(
        link_source,
        "fetch_video_from_url",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("预览不应下载视频")
        ),
    )

    with build_client(
        tmp_path,
        video_link_relevance_checker=LowRelevanceChecker(),
    ) as client:
        store_id = create_store(client)
        response = client.post(
            f"/api/v1/stores/{store_id}/videos/from-url/preview",
            json={"url": "https://v.douyin.com/game/"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "title": "王者荣耀五杀集锦",
        "description": "本周排位精彩操作",
        "relevance": "low",
        "reason": "内容是游戏集锦，与餐饮经营无明显关系",
    }


def test_link_source_prefers_cookie_file_over_local_browser(monkeypatch) -> None:
    from yongge_online.videos.link_source import _cookies_args

    monkeypatch.setenv("YT_DLP_COOKIES_FILE", "/run/secrets/douyin-cookies.txt")
    monkeypatch.setenv("YT_DLP_COOKIES_FROM_BROWSER", "chrome")

    assert _cookies_args() == ["--cookies", "/run/secrets/douyin-cookies.txt"]


def test_douyin_uses_miuistore_when_yt_dlp_fails(monkeypatch) -> None:
    from yongge_online.videos import link_source
    from yongge_online.videos.link_source import FetchedVideo

    def fail_yt_dlp(url, *, max_bytes):
        raise ValueError("platform restriction")

    def fallback(text, *, max_bytes):
        assert text == "抖音分享 https://v.douyin.com/demo123/"
        assert max_bytes == 123
        return FetchedVideo("fallback.mp4", "video/mp4", b"video", "fallback")

    monkeypatch.setattr(link_source, "_fetch_with_yt_dlp", fail_yt_dlp)
    monkeypatch.setattr(link_source, "_fetch_with_miuistore", fallback)

    fetched = link_source.fetch_video_from_url(
        "抖音分享 https://v.douyin.com/demo123/", max_bytes=123
    )
    assert fetched.filename == "fallback.mp4"
    assert fetched.source_provider == "miuistore"
    assert fetched.primary_failure_reason == "yt_dlp_unclassified_failure"


def test_yt_dlp_cookie_failure_is_classified_without_raw_error(monkeypatch) -> None:
    from yongge_online.videos.link_source import _classify_yt_dlp_failure

    monkeypatch.setenv("YT_DLP_COOKIES_FILE", "/run/secrets/douyin-cookies.txt")

    assert (
        _classify_yt_dlp_failure(
            "ERROR: Fresh cookies (not necessarily logged in) are needed",
            phase="probe",
        )
        == "cookie_invalid_or_expired"
    )


def test_non_douyin_does_not_use_miuistore(monkeypatch) -> None:
    from yongge_online.core.errors import DomainError
    from yongge_online.videos import link_source

    monkeypatch.setattr(
        link_source,
        "_fetch_with_yt_dlp",
        lambda url, *, max_bytes: (_ for _ in ()).throw(ValueError("blocked")),
    )
    monkeypatch.setattr(
        link_source,
        "_fetch_with_miuistore",
        lambda text, *, max_bytes: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    with pytest.raises(DomainError) as exc_info:
        link_source.fetch_video_from_url("https://example.com/video", max_bytes=123)

    assert exc_info.value.code == "video_url_unresolvable"


