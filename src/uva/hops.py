"""逐跳探活：司空 → ECS MediaMTX → 本机队列。不打印密码。"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from uva.paths import PROJECT_ROOT
from uva.rtmp_url import redact_rtmp_url
from uva.settings import Settings, load_settings
from uva.store import open_store

logger = logging.getLogger(__name__)

SSH_KEYS = tuple(
    p
    for p in (
        Path(os.environ["UVA_SSH_KEY"]) if os.environ.get("UVA_SSH_KEY") else None,
        Path.home() / ".ssh" / "id_rsa",
        Path.home() / ".ssh" / "id_ed25519",
    )
    if p is not None
)
REMOTE_SCRIPT = PROJECT_ROOT / "deploy" / "edge" / "hops_remote.sh"
PASS_RE = re.compile(r"(pass|password|pwd)=[^ \n&]+", re.I)


def _hop(hid: str, ok: bool, detail: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {"id": hid, "ok": ok, "detail": detail}
    if extra:
        row.update(extra)
    return row


def ssh_target(settings: Settings) -> tuple[str, str]:
    raw = (os.environ.get("UVA_EDGE_SSH") or "").strip()
    if raw:
        if "@" in raw:
            user, host = raw.split("@", 1)
            return user, host
        return "root", raw
    url = settings.rtmp_pull_url or settings.rtmp_publish_url or settings.rtmp_url
    host = urlparse(url).hostname or ""
    return os.environ.get("UVA_EDGE_SSH_USER", "root"), host


def ssh_key() -> Path | None:
    env = (os.environ.get("UVA_EDGE_SSH_KEY") or "").strip()
    if env:
        p = Path(env)
        return p if p.is_file() else None
    for p in SSH_KEYS:
        if p.is_file():
            return p
    return None


def probe_tcp(host: str, port: int = 1935, timeout: float = 5) -> dict[str, Any]:
    if not host:
        return _hop("tcp_1935", False, "没有收流主机，检查 UVA_RTMP_PULL_URL")
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            peer = sock.getpeername()
        return _hop("tcp_1935", True, f"TCP 通 {peer[0]}:{peer[1]}")
    except OSError as exc:
        return _hop("tcp_1935", False, f"TCP 失败 {host}:{port} {exc}")


def probe_rtmp_handshake(host: str, port: int = 1935, timeout: float = 6) -> dict[str, Any]:
    if not host:
        return _hop("rtmp_handshake", False, "没有收流主机")
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"\x03" + b"\x00" * 1536)
            data = sock.recv(4096)
    except OSError as exc:
        return _hop("rtmp_handshake", False, f"握手失败 {exc}")
    if not data:
        return _hop(
            "rtmp_handshake",
            False,
            "TCP 通但 0 字节回来：安全组/云防火墙在边缘丢掉 RTMP 载荷",
        )
    ok = data[0] == 3
    return _hop("rtmp_handshake", ok, f"S0={data[:1].hex()} bytes={len(data)}")


def summarize_conns(payload: dict[str, Any], stream: str) -> dict[str, Any]:
    items = payload.get("items") or payload.get("rtmpConns") or []
    if isinstance(items, dict):
        items = list(items.values())
    publishers: list[dict[str, Any]] = []
    readers: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if stream and path not in (stream, stream.rstrip("/")):
            continue
        rec = {
            "addr": item.get("remoteAddr") or item.get("remote_addr") or "",
            "bytesReceived": item.get("bytesReceived") or item.get("bytes_received"),
            "bytesSent": item.get("bytesSent") or item.get("bytes_sent"),
        }
        state = str(item.get("state") or "")
        if state == "publish":
            publishers.append(rec)
        elif state == "read":
            readers.append(rec)
    return {"publishers": publishers, "readers": readers}


def summarize_path(payload: dict[str, Any], stream: str) -> dict[str, Any]:
    if payload.get("error"):
        return {"ready": False, "error": payload["error"]}
    items = payload.get("items") or payload.get("paths") or []
    if isinstance(items, dict):
        items = list(items.values())
    hit = None
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("path") or "")
        if name == stream or name.rstrip("/") == stream.rstrip("/"):
            hit = item
            break
    if hit is None:
        return {"ready": False, "name": stream, "found": False, "n_paths": len(items)}
    readers = hit.get("readers") or []
    n_readers = len(readers) if isinstance(readers, list) else int(readers or 0)
    return {
        "found": True,
        "name": hit.get("name"),
        "ready": bool(hit.get("ready")),
        "tracks": hit.get("tracks") or [],
        "bytesReceived": hit.get("bytesReceived") or hit.get("bytes_received"),
        "bytesSent": hit.get("bytesSent") or hit.get("bytes_sent"),
        "readers": n_readers,
    }


def _run_ssh(user: str, host: str, key: Path) -> dict[str, Any]:
    script = REMOTE_SCRIPT.read_bytes().replace(b"\r\n", b"\n")
    cmd = [
        "ssh",
        "-o",
        "ConnectTimeout=12",
        "-o",
        "BatchMode=yes",
        "-i",
        str(key),
        f"{user}@{host}",
        "bash -s",
    ]
    proc = subprocess.run(cmd, input=script, capture_output=True, timeout=25)
    text = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = PASS_RE.sub(r"\1=***", proc.stderr.decode("utf-8", "replace")[-800:])
        return {"ok": False, "error": err or text[-800:]}
    try:
        return {"ok": True, "data": json.loads(text)}
    except json.JSONDecodeError:
        return {"ok": False, "error": text[-800:]}


def probe_mediamtx(settings: Settings) -> dict[str, Any]:
    user, host = ssh_target(settings)
    key = ssh_key()
    if not host:
        return _hop("mediamtx", False, "没有 SSH 主机")
    if key is None:
        return _hop("mediamtx", False, "找不到 SSH 私钥（设置 UVA_SSH_KEY 或 ~/.ssh/id_rsa）")
    remote = _run_ssh(user, host, key)
    if not remote.get("ok"):
        return _hop("mediamtx", False, f"SSH 失败 {remote.get('error')}")
    data = remote["data"]
    stream = settings.rtmp_stream or "live/uva"
    path = summarize_path(data.get("paths") or {}, stream)
    conns = summarize_conns(data.get("rtmp_conns") or {}, stream)
    n_pub = len(conns["publishers"])
    n_read = len(conns["readers"])
    service_ok = data.get("service") == "active" and bool(data.get("listen_1935"))
    ready = bool(path.get("ready"))
    if ready:
        pub_addr = conns["publishers"][0]["addr"] if conns["publishers"] else "?"
        detail = (
            f"uva-edge active，{stream} 在线 tracks={path.get('tracks')} "
            f"发布 {n_pub} 路（{pub_addr}）拉流 {n_read} 路 recv={path.get('bytesReceived')}"
        )
    elif path.get("found"):
        detail = f"uva-edge active，{stream} 已配置但当前没有发布者（司空还没推上来）"
    else:
        detail = f"uva-edge active，API 里还没有路径 {stream}"
    extra = {
        "nproc": data.get("nproc"),
        "mem_mb": data.get("mem_mb"),
        "path": path,
        "conns": conns,
        "journal_tail": data.get("journal_tail") or "",
    }
    return _hop("mediamtx", service_ok, detail, extra)


def probe_queue(settings: Settings) -> dict[str, Any]:
    store = open_store(settings)
    runs = store.list_runs(limit=1)
    if not runs:
        return _hop("gpu_queue", True, "本机队列还是空的，还没有 ingest")
    run = runs[0]
    detail = (
        f"队列最新 run={run['run_id']} jobs={run['job_count']} "
        f"done={run['done_count']} failed={run['failed_count']} "
        f"started={run.get('started_at')}"
    )
    return _hop("gpu_queue", True, detail, {"run": run})


def probe_ims(settings: Settings) -> dict[str, Any]:
    store = open_store(settings)
    rows = store.list_recent_ims_pushes(limit=3)
    if not rows:
        return _hop("ims", True, "本机还没有 IMS 写出记录")
    last = rows[0]
    ok = str(last.get("status") or "") in ("ok", "duplicate", "dry_run")
    detail = (
        f"最近一次 {last.get('status')} run={last.get('run_id')} "
        f"job={last.get('job_id')} at={last.get('created_at')}"
    )
    return _hop("ims", ok, detail, {"recent": rows})


def _ffmpeg_tail() -> str:
    log_dir = PROJECT_ROOT / "data" / "runtime" / "logs"
    chunks: list[str] = []
    for name in ("ffmpeg_jpeg.log", "ffmpeg_publish.log"):
        path = log_dir / name
        if not path.is_file():
            continue
        text = PASS_RE.sub(r"\1=***", path.read_text(encoding="utf-8", errors="replace"))
        text = re.sub(r"(rtmp://)[^/@\s]+@", r"\1***@", text)
        lines = [ln for ln in text.splitlines() if ln.strip()][-8:]
        if lines:
            chunks.append(name + ":\n" + "\n".join(lines))
    return "\n\n".join(chunks)


def collect_hops(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    _user, host = ssh_target(settings)
    hops = [
        probe_tcp(host),
        probe_rtmp_handshake(host),
        probe_mediamtx(settings),
        probe_queue(settings),
        probe_ims(settings),
    ]
    mtx = next((h for h in hops if h["id"] == "mediamtx"), {})
    return {
        "host": host,
        "pull": redact_rtmp_url(settings.rtmp_pull_url or settings.rtmp_url),
        "hops": hops,
        "ffmpeg_tail": _ffmpeg_tail(),
        "journal_tail": mtx.get("journal_tail") or "",
        "nproc": mtx.get("nproc"),
        "mem_mb": mtx.get("mem_mb"),
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"收流主机 {report.get('host')}  {report.get('pull')}",
        f"ECS {report.get('nproc') or '?'} 核 / {report.get('mem_mb') or '?'} MB",
        "tcp / 握手 / mediamtx 是此刻；gpu_queue / ims 是本机库里最新记录",
        "",
    ]
    for hop in report.get("hops") or []:
        mark = "OK" if hop.get("ok") else "FAIL"
        lines.append(f"[{mark}] {hop['id']}: {hop['detail']}")
    ffmpeg = (report.get("ffmpeg_tail") or "").strip()
    if ffmpeg:
        lines += ["", "本机 ffmpeg 日志尾（已打码）", ffmpeg]
    journal = (report.get("journal_tail") or "").strip()
    if journal:
        lines += ["", "ECS MediaMTX 日志尾（已打码）", journal[-2000:]]
    return "\n".join(lines)
