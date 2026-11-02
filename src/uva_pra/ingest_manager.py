"""后台 RTMP 收流（支持本机直连，不经 ECS 中转）。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uva.contract import new_id
from uva.rtmp import run_simulated_rtmp
from uva.settings import Settings, load_settings

from uva_pra.config import PraConfig, load_pra_config
from uva_pra.video_meta import video_duration_sec

logger = logging.getLogger(__name__)

# 模拟 RTMP 推流启动 + 首帧等待（秒）
_SIMULATE_STARTUP_BUFFER_S = 8.0

# 收流进行中轮询已入队帧数（秒）
_FRAME_POLL_INTERVAL_S = 1.5


def _worker_until_empty_for_mode(mode: str) -> bool:
    """RTMP 类收流与识别应并行；成片/文件夹一次性入队可用 until-empty。"""
    return mode in ("file", "image_folder")


def _try_start_worker_for_ingest(mode: str) -> str | None:
    from uva_pra.worker_manager import get_worker_manager

    until_empty = _worker_until_empty_for_mode(mode)
    try:
        st = get_worker_manager().ensure_running(until_empty=until_empty)
        if st.get("running"):
            return None
        return "Worker 启动后未处于运行状态"
    except Exception as exc:
        logger.warning("auto-start worker for ingest failed: %s", exc)
        return str(exc)


@dataclass
class IngestState:
    running: bool = False
    mode: str = ""
    run_id: str | None = None
    error: str | None = None
    finished: bool = False
    frames_ingested: int = 0
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class IngestManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state = IngestState()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.state.running,
                "mode": self.state.mode,
                "run_id": self.state.run_id,
                "error": self.state.error,
                "finished": self.state.finished,
                "frames_ingested": self.state.frames_ingested,
                "message": self.state.message,
                **self.state.extra,
            }

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self.state.running = False

    def reset_status(self) -> None:
        """清空收流状态展示（测试数据重置后调用）。"""
        with self._lock:
            self._stop.clear()
            self.state = IngestState()

    def start(
        self,
        *,
        mode: str,
        run_id: str | None = None,
        duration_s: float | None = None,
        video_path: str | None = None,
        folder_path: str | None = None,
        pull_url: str | None = None,
        cfg: PraConfig | None = None,
    ) -> dict[str, Any]:
        cfg = cfg or load_pra_config()
        with self._lock:
            if self.state.running:
                raise RuntimeError("收流已在运行，请先停止")
            self._stop.clear()
            self.state = IngestState(
                running=True,
                mode=mode,
                run_id=run_id or new_id("run_"),
                message="收流进行中…",
            )

        def _poll_ingested_frames(rid: str, settings: Settings) -> None:
            from uva.store import open_store

            store = open_store(settings)
            while not self._stop.is_set():
                with self._lock:
                    if not self.state.running or self.state.run_id != rid:
                        return
                try:
                    cur = store._conn.execute(
                        "select count(*) from jobs where run_id=?",
                        (rid,),
                    )
                    n = int(cur.fetchone()[0])
                    with self._lock:
                        if self.state.run_id == rid:
                            self.state.frames_ingested = n
                            if self.state.running and n == 0 and self.state.mode in (
                                "direct_local",
                                "edge_relay",
                            ):
                                self.state.message = (
                                    "等待 RTMP 发布到 live/uva（尚未拉到首帧，队列为 0）。"
                                    "直连模式请把司空/推流端指到本机公网 1935；"
                                    "若流在 ECS 上请改用 edge_relay。"
                                    "可查 data/runtime/logs/mediamtx.log。"
                                )
                            elif self.state.running and n == 0 and self.state.mode == "remote_pull":
                                self.state.message = (
                                    "正在从自定义拉流 URL 抽帧（尚未入队）。"
                                    "若长时间为 0，查 ffmpeg_jpeg.log（H265/过期 token 等）。"
                                )
                            elif self.state.running and n > 0:
                                self.state.message = (
                                    f"收流进行中，Worker 与抽帧并行识别… 已入队 {n} 帧"
                                )
                except Exception:
                    logger.debug("frame poll failed", exc_info=True)
                time.sleep(_FRAME_POLL_INTERVAL_S)

        def _worker() -> None:
            from uva_pra.bootstrap import ensure_uva_paths

            ensure_uva_paths()
            import os

            os.environ["UVA_FRAME_INTERVAL_S"] = str(cfg.ingest.rtmp_frame_interval_sec)
            settings = load_settings()
            rid = self.state.run_id
            frames = 0
            custom_pull = (pull_url or cfg.ingest.rtmp_custom_pull_url or "").strip()
            if mode == "remote_pull":
                from uva.rtmp_url import redact_rtmp_url

                if not custom_pull:
                    raise ValueError(
                        "remote_pull 需要拉流地址：在下方填写或保存到配置 ingest.rtmp_custom_pull_url"
                    )
                if not custom_pull.lower().startswith("rtmp://"):
                    raise ValueError("拉流地址须以 rtmp:// 开头")
                with self._lock:
                    self.state.extra["pull"] = redact_rtmp_url(custom_pull)
            worker_err = _try_start_worker_for_ingest(mode)
            with self._lock:
                if worker_err:
                    self.state.message = (
                        f"收流进行中…（Worker 未自动启动: {worker_err}；"
                        "请在「配置」页点「启动 Worker」）"
                    )
                else:
                    self.state.message = "收流进行中，Worker 与抽帧并行识别…"
            poll_thread: threading.Thread | None = None
            if mode != "file":
                poll_thread = threading.Thread(
                    target=_poll_ingested_frames,
                    args=(rid, settings),
                    name="uva_pra_ingest_poll",
                    daemon=True,
                )
                poll_thread.start()
            try:
                if mode == "direct_local":
                    # 本机/服务器起 MediaMTX，外部 RTMP 直推，无需 ECS 中转
                    run_simulated_rtmp(
                        run_id=rid,
                        duration_s=duration_s,
                        settings=settings,
                        start_local_server=True,
                        do_publish=False,
                        stop_event=self._stop,
                        frame_interval_s=cfg.ingest.rtmp_frame_interval_sec,
                    )
                elif mode == "edge_relay":
                    run_simulated_rtmp(
                        run_id=rid,
                        duration_s=duration_s,
                        settings=settings,
                        start_local_server=False,
                        do_publish=False,
                        stop_event=self._stop,
                        frame_interval_s=cfg.ingest.rtmp_frame_interval_sec,
                    )
                elif mode == "remote_pull":
                    run_simulated_rtmp(
                        run_id=rid,
                        duration_s=duration_s,
                        settings=settings,
                        pull_url=custom_pull,
                        start_local_server=False,
                        do_publish=False,
                        stop_event=self._stop,
                        frame_interval_s=cfg.ingest.rtmp_frame_interval_sec,
                    )
                elif mode == "simulate":
                    video = Path(video_path) if video_path else None
                    if video is None or not video.is_file():
                        raise FileNotFoundError(f"模拟视频不存在: {video_path}")
                    sim_duration = duration_s
                    if sim_duration is None:
                        sim_duration = video_duration_sec(video) + _SIMULATE_STARTUP_BUFFER_S
                    run_simulated_rtmp(
                        video=video,
                        run_id=rid,
                        duration_s=sim_duration,
                        settings=settings,
                        start_local_server=True,
                        do_publish=True,
                        stop_event=self._stop,
                        frame_interval_s=cfg.ingest.rtmp_frame_interval_sec,
                    )
                elif mode == "file":
                    from uva.ingest import ingest_path

                    if not video_path:
                        raise ValueError("file 模式需要 video_path")
                    video = Path(video_path)
                    _, jobs = ingest_path(
                        video,
                        run_id=rid,
                        settings=settings,
                    )
                    frames = len(jobs)
                    with self._lock:
                        self.state.frames_ingested = frames
                elif mode == "image_folder":
                    from uva.ingest import ingest_folder

                    if not folder_path:
                        raise ValueError("image_folder 模式需要 folder_path")
                    with self._lock:
                        self.state.message = "正在扫描文件夹并复制入队（请稍候）…"
                    _, jobs = ingest_folder(
                        folder_path,
                        run_id=rid,
                        settings=settings,
                        recursive=True,
                    )
                    frames = len(jobs)
                    with self._lock:
                        self.state.frames_ingested = frames
                        self.state.extra["folder"] = str(Path(folder_path).resolve())
                else:
                    raise ValueError(f"未知 rtmp_mode: {mode}")

                if mode not in ("file", "image_folder"):
                    from uva.store import open_store

                    store = open_store(settings)
                    cur = store._conn.execute(
                        "select count(*) from jobs where run_id=?",
                        (rid,),
                    )
                    frames = int(cur.fetchone()[0])
                    with self._lock:
                        self.state.frames_ingested = frames
            except Exception as exc:
                logger.exception("ingest failed")
                with self._lock:
                    self.state.error = str(exc)
                    self.state.message = f"收流失败: {exc}"
            else:
                from uva_pra.worker_manager import get_worker_manager

                ws = get_worker_manager().status()
                with self._lock:
                    self.state.finished = True
                    if ws.get("running"):
                        self.state.message = (
                            f"收流已结束，共入队 {frames} 帧（run={rid}）。"
                            "识别与收流并行进行，剩余任务由 Worker 继续处理，可在「运行」页刷新查看。"
                        )
                    else:
                        self.state.message = (
                            f"收流已结束，入队 {frames} 帧（run={rid}）。"
                            "Worker 未运行，请在「配置」页启动 Worker，或执行 .\\run_pra.ps1 worker"
                        )
            finally:
                with self._lock:
                    self.state.running = False
                if poll_thread is not None:
                    poll_thread.join(timeout=1.0)

        self._thread = threading.Thread(target=_worker, name="uva_pra_ingest", daemon=True)
        self._thread.start()
        return self.status()


_manager: IngestManager | None = None


def get_ingest_manager() -> IngestManager:
    global _manager
    if _manager is None:
        _manager = IngestManager()
    return _manager
