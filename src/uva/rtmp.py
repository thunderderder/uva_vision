"""本机 MediaMTX + ffmpeg：协议级模拟 RTMP，抽 JPEG 入同一 Job 队列。"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from uva.contract import new_id
from uva.ffmpeg_bin import ensure_ffmpeg, find_ffmpeg
from uva.ingest import ingest_image
from uva.paths import BIN_DIR, PROJECT_ROOT
from uva.rtmp_url import (
    _LOCAL_MTX_HOSTS,
    redact_rtmp_url,
    uses_mtx_query_auth,
    with_rtmp_auth,
)
from uva.settings import Settings, load_settings
from uva.store import Store, open_store
from uva.video_telemetry import load_cues_for_video, telemetry_at_ms

logger = logging.getLogger(__name__)

# 直播按 1080p 推。成片 4K 应先压到 1920 再 -re，否则实时编码会掉帧。
RTMP_SCALE_WIDTH = 1920

MEDIAMTX_ZIP = "https://github.com/bluenviron/mediamtx/releases/download/v1.20.1/mediamtx_v1.20.1_windows_amd64.zip"


def which_tool(name: str) -> Path | None:
    if name == "ffmpeg":
        return find_ffmpeg()
    found = shutil.which(name)
    if found:
        return Path(found)
    local = BIN_DIR / f"{name}.exe"
    if local.is_file():
        return local
    return None


def ensure_mediamtx() -> Path:
    exe = which_tool("mediamtx")
    if exe is not None:
        return exe
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = BIN_DIR / "mediamtx.exe"
    if dest.is_file():
        return dest
    zip_path = BIN_DIR / "mediamtx.zip"
    urllib.request.urlretrieve(MEDIAMTX_ZIP, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.endswith("mediamtx.exe") or member.endswith("mediamtx"):
                zf.extract(member, BIN_DIR)
                extracted = BIN_DIR / member
                extracted.replace(dest)
                break
    if not dest.is_file():
        raise FileNotFoundError("下载 MediaMTX 后仍找不到 mediamtx.exe")
    return dest


def default_video() -> Path:
    folder = PROJECT_ROOT / "data" / "test_video"
    videos = sorted(folder.glob("*.mp4"))
    if not videos:
        raise FileNotFoundError(f"没有测试视频: {folder}")
    return videos[0]


def mediamtx_config_path() -> Path:
    return PROJECT_ROOT / "scripts" / "mediamtx.yml"


def _log_dir() -> Path:
    path = PROJECT_ROOT / "data" / "runtime" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _mtx_hosts(settings: Settings) -> frozenset[str]:
    hosts: set[str] = set(_LOCAL_MTX_HOSTS)
    for raw in (settings.rtmp_url, settings.rtmp_pull_url, settings.rtmp_publish_url):
        raw = (raw or "").strip()
        if not raw:
            continue
        host = (urlparse(raw).hostname or "").lower()
        if host:
            hosts.add(host)
    return frozenset(hosts)


def resolve_rtmp_endpoint(url: str, settings: Settings) -> str:
    """拉流/推流地址：仅对自有 MTX 主机追加 UVA_RTMP_USER/PASS。"""
    url = (url or "").strip()
    if not url:
        return url
    if uses_mtx_query_auth(url, _mtx_hosts(settings)):
        return with_rtmp_auth(url, settings.rtmp_user, settings.rtmp_password)
    return url


def publish_endpoint(settings: Settings, override: str | None = None) -> str:
    base = (override or settings.rtmp_publish_url or settings.rtmp_url).strip()
    return resolve_rtmp_endpoint(base, settings)


def pull_endpoint(settings: Settings, override: str | None = None) -> str:
    base = (override or settings.rtmp_pull_url or settings.rtmp_url).strip()
    return resolve_rtmp_endpoint(base, settings)


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def start_mediamtx() -> subprocess.Popen:
    exe = ensure_mediamtx()
    cfg = mediamtx_config_path()
    log = (_log_dir() / "mediamtx.log").open("w", encoding="utf-8")
    return subprocess.Popen(
        [str(exe), str(cfg)],
        cwd=str(PROJECT_ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def start_ffmpeg_loop(video: Path, rtmp_url: str, width: int = RTMP_SCALE_WIDTH) -> subprocess.Popen:
    ffmpeg = ensure_ffmpeg()
    log = (_log_dir() / "ffmpeg_publish.log").open("w", encoding="utf-8")
    return subprocess.Popen(
        [
            str(ffmpeg),
            "-re",
            "-stream_loop",
            "-1",
            "-i",
            str(video),
            "-an",
            "-vf",
            f"scale={width}:-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "flv",
            rtmp_url,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def _wait_for_rtmp_grabber(
    rtmp_url: str,
    out_dir: Path,
    interval_s: float,
    *,
    stop_event=None,
    max_wait_s: float | None = None,
) -> subprocess.Popen | None:
    """外部推流：无人发布时 ffmpeg 拉流会秒退，循环拉起直到首帧或停止。"""
    deadline = None if max_wait_s is None else time.time() + max_wait_s
    grabber: subprocess.Popen | None = None
    while True:
        if stop_event is not None and stop_event.is_set():
            _stop(grabber)
            return None
        if deadline is not None and time.time() >= deadline:
            _stop(grabber)
            raise RuntimeError(
                "等待外部 RTMP 推流超时。确认发布端已推到 live/uva，或改用 simulate 模式本机 mp4 演练"
            )
        if grabber is None or grabber.poll() is not None:
            grabber = start_ffmpeg_jpeg(rtmp_url, out_dir, interval_s)
        for path in out_dir.glob("*.jpg"):
            if path.stat().st_size >= 1024:
                return grabber
        time.sleep(1.0)


def start_ffmpeg_jpeg(rtmp_url: str, out_dir: Path, interval_s: float) -> subprocess.Popen:
    ffmpeg = ensure_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "rtmp_%08d.jpg")
    vf = f"fps=1/{interval_s}"
    log = (_log_dir() / "ffmpeg_jpeg.log").open("w", encoding="utf-8")
    local = "127.0.0.1" in rtmp_url or "localhost" in rtmp_url
    timeout = "15000000" if local else "30000000"
    return subprocess.Popen(
        [
            str(ffmpeg),
            "-rw_timeout",
            timeout,
            "-i",
            rtmp_url,
            "-vf",
            vf,
            "-q:v",
            "3",
            "-y",
            pattern,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def watch_jpegs(
    watch_dir: Path,
    *,
    run_id: str,
    store: Store,
    settings: Settings,
    stop_after: float | None = None,
    cues=None,
    stop_event=None,
) -> int:
    watch_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    started = time.time()
    count = 0
    interval = settings.frame_interval_s
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        for path in sorted(watch_dir.glob("*.jpg")):
            if path.name in seen:
                continue
            if path.stat().st_size < 1024:
                continue
            seen.add(path.name)
            tele = telemetry_at_ms(cues or [], count * interval * 1000.0, water_name=settings.water_name or None)
            ingest_image(
                path,
                run_id=run_id,
                store=store,
                settings=settings,
                source_type="rtmp",
                frame_index=count,
                captured_at=tele.captured_at_local,
                telemetry=tele,
            )
            if count == 0:
                logger.info("hop ecs_first_frame run_id=%s file=%s", run_id, path.name)
            count += 1
        if stop_after is not None and (time.time() - started) >= stop_after:
            break
        time.sleep(0.4)
    return count


def run_publish(
    *,
    video: Path | None = None,
    url: str | None = None,
    duration_s: float | None = None,
    settings: Settings | None = None,
) -> str:
    """只把成片按实时速率推到收流节点。GPU 与 MediaMTX 都不在这台机器上也能用。"""
    settings = settings or load_settings()
    video = video or default_video()
    dest = publish_endpoint(settings, url)
    if not dest:
        raise ValueError("没有推流地址。设置 UVA_RTMP_PUBLISH_URL 或传入 --url")
    width = settings.rtmp_scale_width or RTMP_SCALE_WIDTH
    publisher = start_ffmpeg_loop(video, dest, width=width)
    time.sleep(1.0)
    if publisher.poll() is not None:
        raise RuntimeError("ffmpeg 推流失败，见 data/runtime/logs/ffmpeg_publish.log")
    logger.info("publishing %s -> %s", video.name, redact_rtmp_url(dest))
    try:
        if duration_s is None:
            publisher.wait()
        else:
            time.sleep(duration_s)
    finally:
        _stop(publisher)
    return dest


def run_simulated_rtmp(
    *,
    video: Path | None = None,
    run_id: str | None = None,
    duration_s: float | None = None,
    settings: Settings | None = None,
    pull_url: str | None = None,
    publish_url: str | None = None,
    start_local_server: bool = True,
    do_publish: bool = True,
    stop_event=None,
    frame_interval_s: float | None = None,
) -> str:
    settings = settings or load_settings()
    interval_s = frame_interval_s if frame_interval_s is not None else settings.frame_interval_s
    store = open_store(settings)
    run_id = run_id or new_id("run_")
    jpeg_dir = settings.frames_dir / run_id / "rtmp_watch"
    width = settings.rtmp_scale_width or RTMP_SCALE_WIDTH
    grab_url = pull_endpoint(settings, pull_url)
    pub_url = publish_endpoint(settings, publish_url)
    cues = []
    if video is not None and video.is_file():
        cues = load_cues_for_video(video, settings.runtime_dir / "subtitles")
    elif do_publish:
        video = video or default_video()
        cues = load_cues_for_video(video, settings.runtime_dir / "subtitles")
    store.add_event(
        "run_start",
        run_id=run_id,
        payload={
            "kind": "rtmp",
            "video": str(video) if video else None,
            "pull": redact_rtmp_url(grab_url),
            "publish": redact_rtmp_url(pub_url) if do_publish else None,
            "local_mtx": start_local_server,
            "scale_width": width,
            "srt_cues": len(cues),
        },
    )
    mtx = publisher = grabber = None
    try:
        if start_local_server:
            mtx = start_mediamtx()
            time.sleep(1.5)
            if mtx.poll() is not None:
                raise RuntimeError("MediaMTX 启动失败，见 data/runtime/logs/mediamtx.log")
            grab_url = pub_url = resolve_rtmp_endpoint(settings.rtmp_url, settings)
        # 收流节点上「先拉后推」会立刻 EOF：没人发布时 RTMP play 不会挂起。
        # 本机模拟同理，先让发布端起来再抽 JPEG。
        if do_publish:
            if video is None or not video.is_file():
                raise FileNotFoundError("推流需要 --video 或 data/test_video 里的 mp4")
            publisher = start_ffmpeg_loop(video, pub_url, width=width)
            time.sleep(2.5)
            if publisher.poll() is not None:
                raise RuntimeError("ffmpeg 推流失败，见 data/runtime/logs/ffmpeg_publish.log")
            logger.info("hop ecs_publish %s", redact_rtmp_url(pub_url))
        logger.info("hop ecs_pull %s interval=%ss", redact_rtmp_url(grab_url), interval_s)
        if do_publish:
            grabber = start_ffmpeg_jpeg(grab_url, jpeg_dir, interval_s)
            time.sleep(1.0)
            if grabber.poll() is not None:
                raise RuntimeError("ffmpeg 拉流失败，见 data/runtime/logs/ffmpeg_jpeg.log")
        else:
            grabber = _wait_for_rtmp_grabber(
                grab_url,
                jpeg_dir,
                interval_s,
                stop_event=stop_event,
                max_wait_s=duration_s,
            )
            if grabber is None:
                return run_id
        n = watch_jpegs(
            jpeg_dir,
            run_id=run_id,
            store=store,
            settings=settings,
            stop_after=duration_s,
            cues=cues,
            stop_event=stop_event,
        )
        if n == 0 and (stop_event is None or not stop_event.is_set()):
            raise RuntimeError("RTMP 抽到 0 张 JPEG，见 data/runtime/logs/ffmpeg_*.log")
        logger.info("hop ecs_ingest run_id=%s frames=%s gps_cues=%s", run_id, n, len(cues))
    finally:
        for proc in (grabber, publisher, mtx):
            _stop(proc)
    return run_id
