"""链接 → 视频文件:移植自 FluentFlow `backend/core/video_source.py`(§23 2026-07-23 决策)。

用 yt-dlp 解析分享链接(抖音等)并下载成本地视频字节,供现有上传/解析流水复用。
运行依赖:后端 venv 内的 `yt_dlp`;抖音风控兜底可设
`YT_DLP_COOKIES_FILE`（生产环境）或 `YT_DLP_COOKIES_FROM_BROWSER`（本地开发）。
"""

import html
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from yongge_online.core.errors import DomainError

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s　<>\"']+")
_MIUISTORE_ORIGIN = "https://sph.miuistore.com"

_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
    ".avi": "video/x-msvideo",
}


@dataclass
class FetchedVideo:
    filename: str
    content_type: str
    content: bytes
    title: str
    source_provider: str = "yt-dlp"
    primary_failure_reason: str | None = None


@dataclass
class VideoLinkMetadata:
    title: str
    description: str | None = None


class YtDlpFailure(ValueError):
    """yt-dlp 的可观测失败；只保留分类，不向日志泄露原始 stderr。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def extract_first_url(text: str) -> str | None:
    """分享文案里常混杂表情和口令,只取第一个 http(s) 链接。"""
    match = _URL_RE.search(text or "")
    return match.group(0).rstrip("，。;；,)]】") if match else None


def _cookies_args() -> list[str]:
    """优先使用受控 Cookie 文件；本地才回退到浏览器配置。"""
    cookie_file = os.environ.get("YT_DLP_COOKIES_FILE", "").strip()
    if cookie_file:
        return ["--cookies", cookie_file]

    browser = os.environ.get("YT_DLP_COOKIES_FROM_BROWSER", "").strip()
    return ["--cookies-from-browser", browser] if browser else []


def cookies_configured() -> bool:
    return bool(_cookies_args())


def _classify_yt_dlp_failure(stderr: str, *, phase: str) -> str:
    """把 yt-dlp 稳定错误提示压缩成无敏感信息的运维分类。"""
    message = (stderr or "").casefold()
    cookie_markers = (
        "fresh cookies",
        "cookies are no longer valid",
        "cookies have expired",
        "not necessarily logged in",
        "login required",
        "please log in",
        "please sign in",
        "sign in to confirm",
        "not logged in",
    )
    if any(marker in message for marker in cookie_markers):
        return "cookie_invalid_or_expired" if cookies_configured() else "cookie_missing"
    return f"yt_dlp_{phase}_failed"


def _run(args: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "yt_dlp", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _probe_with_yt_dlp(url: str) -> dict:
    probe = _run(
        ["--dump-single-json", "--skip-download", "--no-playlist", *_cookies_args(), url],
        timeout=60,
    )
    if probe.returncode != 0:
        raise YtDlpFailure(_classify_yt_dlp_failure(probe.stderr, phase="probe"))
    try:
        return json.loads(probe.stdout)
    except ValueError as exc:
        raise YtDlpFailure("yt_dlp_invalid_metadata") from exc


def _is_douyin_url(url: str) -> bool:
    # 抖音官方分享域不止 douyin.com:网页端"复制链接"常给 iesdouyin.com,
    # 漏掉它会让 Miuistore 兜底整条被跳过。
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return (
        host in ("douyin.com", "iesdouyin.com")
        or host.endswith(".douyin.com")
        or host.endswith(".iesdouyin.com")
    )


def _fetch_text(url: str, *, timeout: int = 45) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 PocketMentor/1.0",
            "Accept": "text/html,application/json,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_miuistore_links(page_html: str) -> list[str]:
    return [
        html.unescape(match.group(1)).strip()
        for match in re.finditer(r'href="([^"]+)"', page_html or "", re.I)
        if match.group(1).startswith(("http://", "https://"))
    ]


def _parse_miuistore_field(page_html: str, label: str) -> str | None:
    pattern = re.compile(
        rf"{re.escape(label)}：\s*</div>\s*<div[^>]*class=['\"][^'\"]*\bcol-value\b[^'\"]*['\"][^>]*>([\s\S]*?)</div>",
        re.I,
    )
    match = pattern.search(page_html or "")
    if not match:
        return None
    without_tags = re.sub(r"<[^>]*>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip() or None


def _resolve_miuistore_video(text: str) -> tuple[str, str | None]:
    """使用 FluentFlow 已验证的 Miuistore 两步解析，返回可下载的 MP4 直链。"""
    check_url = f"{_MIUISTORE_ORIGIN}/sph/public/dy-check?{urllib.parse.urlencode({'data': text})}"
    checked = json.loads(_fetch_text(check_url))
    if checked.get("error") != 0 or not checked.get("url"):
        raise ValueError("Miuistore 未返回可解析链接")

    query_url = urllib.parse.urljoin(_MIUISTORE_ORIGIN, str(checked["url"]))
    query_params = urllib.parse.parse_qs(urllib.parse.urlparse(query_url).query)
    encrypted_url = (query_params.get("url") or [None])[0]
    if not encrypted_url:
        raise ValueError("Miuistore 响应缺少解析参数")

    result_query = urllib.parse.urlencode({"url": encrypted_url})
    result_url = f"{_MIUISTORE_ORIGIN}/sph/public/dy-r?{result_query}"
    page_html = _fetch_text(result_url)
    download_url = next(
        (
            item
            for item in _parse_miuistore_links(page_html)
            if any(
                marker in item
                for marker in ("mime_type=video_mp4", "douyinvod.com", "/aweme/v1/play/")
            )
        ),
        None,
    )
    if not download_url:
        raise ValueError("Miuistore 未返回 MP4 下载地址")
    return download_url, _parse_miuistore_field(page_html, "视频标题")


def _download_direct_mp4(url: str, *, max_bytes: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 PocketMentor/1.0",
            "Referer": "https://www.douyin.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        content_length = int(response.headers.get("content-length") or 0)
        if content_length > max_bytes:
            raise ValueError("视频超过大小限制")
        chunks: list[bytes] = []
        downloaded = 0
        while chunk := response.read(1024 * 1024):
            downloaded += len(chunk)
            if downloaded > max_bytes:
                raise ValueError("视频超过大小限制")
            chunks.append(chunk)
    return b"".join(chunks)


def _fetch_with_miuistore(text: str, *, max_bytes: int) -> FetchedVideo:
    download_url, title = _resolve_miuistore_video(text)
    return FetchedVideo(
        filename=f"{title or '链接视频'}.mp4",
        content_type="video/mp4",
        content=_download_direct_mp4(download_url, max_bytes=max_bytes),
        title=title or "链接视频",
        source_provider="miuistore",
    )


def _fetch_with_yt_dlp(url: str, *, max_bytes: int) -> FetchedVideo:
    """解析元信息并下载单条 MP4；失败时由调用方决定是否切换兜底策略。"""
    info = _probe_with_yt_dlp(url)
    title = str(info.get("title") or "链接视频").strip()[:120]

    with tempfile.TemporaryDirectory(prefix="pm-link-") as tmp:
        out_tmpl = str(Path(tmp) / "video.%(ext)s")
        download = _run(
            [
                "-f", "b[ext=mp4]/bv*[ext=mp4]+ba/b",
                "--no-playlist",
                "--max-filesize", str(max_bytes),
                "-o", out_tmpl,
                *_cookies_args(),
                url,
            ],
            timeout=240,
        )
        files = [p for p in Path(tmp).iterdir() if p.is_file()]
        if download.returncode != 0 or not files:
            raise YtDlpFailure(
                _classify_yt_dlp_failure(download.stderr, phase="download")
            )
        video_path = max(files, key=lambda p: p.stat().st_size)
        suffix = video_path.suffix.lower()
        content_type = _CONTENT_TYPES.get(suffix)
        if content_type is None:
            raise DomainError(
                f"暂不支持 {suffix or '未知'} 格式的链接视频",
                code="invalid_video",
                status_code=422,
            )
        content = video_path.read_bytes()

    return FetchedVideo(
        filename=f"{title}{suffix}" if title else video_path.name,
        content_type=content_type,
        content=content,
        title=title,
    )


def preview_video_url(text: str) -> VideoLinkMetadata:
    """只解析链接元数据，不下载视频文件。"""
    url = extract_first_url(text)
    if not url:
        raise DomainError("没有识别到有效的视频链接", code="invalid_video_url", status_code=422)

    try:
        info = _probe_with_yt_dlp(url)
        title = str(info.get("title") or "未识别到视频标题").strip()[:200]
        description = str(info.get("description") or "").strip()[:1000] or None
        return VideoLinkMetadata(title=title, description=description)
    except Exception as yt_dlp_error:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if _is_douyin_url(url):
            try:
                _, title = _resolve_miuistore_video(text)
                return VideoLinkMetadata(title=title or "未识别到视频标题")
            except Exception as fallback_error:
                logger.warning(
                    "video_url_preview_failed host=%s primary=%s fallback=%s",
                    host,
                    getattr(yt_dlp_error, "reason", type(yt_dlp_error).__name__),
                    fallback_error,
                )
        else:
            logger.warning(
                "video_url_preview_failed host=%s primary=%s fallback=skipped_non_douyin",
                host,
                getattr(yt_dlp_error, "reason", type(yt_dlp_error).__name__),
            )
        raise DomainError(
            "无法读取视频信息：可能链接已过期、视频已下架或平台限制了访问",
            code="video_url_unresolvable",
            status_code=422,
        ) from yt_dlp_error


def fetch_video_from_url(text: str, *, max_bytes: int) -> FetchedVideo:
    """同步执行：yt-dlp 优先；抖音链接失败时 Miuistore 解析直链兜底。"""
    url = extract_first_url(text)
    if not url:
        raise DomainError("没有识别到有效的视频链接", code="invalid_video_url", status_code=422)

    try:
        return _fetch_with_yt_dlp(url, max_bytes=max_bytes)
    except DomainError:
        raise
    except Exception as yt_dlp_error:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        primary_reason = (
            yt_dlp_error.reason
            if isinstance(yt_dlp_error, YtDlpFailure)
            else "yt_dlp_unclassified_failure"
        )
        if _is_douyin_url(url):
            try:
                fetched = _fetch_with_miuistore(text, max_bytes=max_bytes)
                fetched.source_provider = "miuistore"
                fetched.primary_failure_reason = primary_reason
                return fetched
            except Exception as fallback_error:
                logger.warning(
                    "video_url_fetch_failed host=%s primary=%s fallback=%s",
                    host,
                    primary_reason,
                    fallback_error,
                )
        else:
            logger.warning(
                "video_url_fetch_failed host=%s primary=%s fallback=skipped_non_douyin",
                host,
                primary_reason,
            )
        raise DomainError(
            "链接解析失败：可能视频已下架、链接过期或平台限制了访问",
            code="video_url_unresolvable",
            status_code=422,
        ) from yt_dlp_error


