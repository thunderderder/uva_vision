"""本机 GPU worker 子进程（由工作台启停，便于改配置后重启）。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from uva_pra.bootstrap import PROJECT_ROOT, PRA_ROOT

logger = logging.getLogger(__name__)

LOG_PATH = PROJECT_ROOT / "data" / "runtime" / "logs" / "pra_worker.log"


def _python_exe() -> Path:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        candidate = PROJECT_ROOT / rel.replace("/", os.sep)
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(PRA_ROOT / "src")]
    existing = env.get("PYTHONPATH", "")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


class WorkerManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._until_empty = False

    def _is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _last_log_tail(self, max_lines: int = 28) -> str:
        if not LOG_PATH.is_file():
            return ""
        try:
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-max_lines:])

    def _worker_phase(self, running: bool, tail: str, exit_code: int | None) -> str:
        if not running:
            if exit_code is not None and exit_code != 0:
                # Windows 原生崩溃常为 0xC0000005（十进制 3221225477 或带符号 -1073741819）
                if exit_code in (-1073741819, 3221225477, -1073740791):
                    return "crashed_native"
                return "exited_error"
            return "stopped"
        if "worker 启动" in tail or "hop gpu_job" in tail:
            return "ready"
        if "Loading Qwen" in tail or "Loading weights" in tail:
            return "loading_vlm"
        if "worker start" in tail or "FutureWarning" in tail:
            return "starting"
        return "starting"

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._is_running()
            exit_code = None
            if self._proc is not None and not running:
                exit_code = self._proc.poll()
            tail = self._last_log_tail()
            phase = self._worker_phase(running, tail, exit_code)
            return {
                "running": running,
                "pid": self._proc.pid if running and self._proc else None,
                "exit_code": exit_code,
                "phase": phase,
                "until_empty": self._until_empty,
                "log_path": str(LOG_PATH),
                "log_tail": tail,
                "managed": True,
            }

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=5)
            self._proc = None
        return self.status()

    def start(self, *, until_empty: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._is_running():
                raise RuntimeError("worker 已在运行，请先停止或点重启")
            self._until_empty = until_empty
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            log_file = LOG_PATH.open("a", encoding="utf-8")
            log_file.write("\n--- worker start ---\n")
            log_file.flush()
            args = [str(_python_exe()), "-m", "uva_pra", "worker"]
            if until_empty:
                args.append("--until-empty")
            self._proc = subprocess.Popen(
                args,
                cwd=str(PROJECT_ROOT),
                env=_child_env(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            logger.info("pra worker started pid=%s until_empty=%s", self._proc.pid, until_empty)
        return self.status()

    def restart(self, *, until_empty: bool = False) -> dict[str, Any]:
        self.stop()
        return self.start(until_empty=until_empty)

    def ensure_running(self, *, until_empty: bool = False) -> dict[str, Any]:
        """若未运行则启动；已运行时复用现有进程（与收流并行消费队列）。"""
        if self.status().get("running"):
            return self.status()
        return self.start(until_empty=until_empty)


_manager: WorkerManager | None = None


def get_worker_manager() -> WorkerManager:
    global _manager
    if _manager is None:
        _manager = WorkerManager()
    return _manager
