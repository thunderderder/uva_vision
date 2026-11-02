"""读取飞流推送落盘日志（供工作台展示 / 发给对方技术）。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from uva.settings import Settings

_PICDATA_OMIT_PREFIX = "<base64 已省略，仅展示联调字段；完整 picData 见落盘文件 "


def display_document(doc: dict[str, Any], *, log_path: str | None = None) -> dict[str, Any]:
    """工作台展示 / 复制用：保留 meta、attempts、response 等，picData 只留长度说明。"""
    out = copy.deepcopy(doc)
    req = out.get("request")
    if isinstance(req, dict) and isinstance(req.get("picData"), str):
        raw = req["picData"]
        tail = f"{log_path}>" if log_path else "push_records/feiliu_*.json>"
        req["picData"] = f"{_PICDATA_OMIT_PREFIX}{tail} （{len(raw)} 字符）"
    return out


def _paths_from_result(result: dict[str, Any] | None) -> list[Path]:
    paths: list[Path] = []
    if not result:
        return paths
    push = result.get("feiliu_push") or {}
    for item in push.get("items") or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("log_path") or item.get("path")
        if raw:
            paths.append(Path(str(raw)))
    return paths


def _read_document(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if "log_version" not in data and "request" in data:
        return {
            "log_version": 0,
            "legacy": True,
            "status": data.get("status"),
            "request": data.get("request"),
            "response": data.get("response"),
        }
    return data


def _scan_push_dir_for_job(push_dir: Path, job_id: str) -> list[Path]:
    if not push_dir.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(push_dir.glob("feiliu_*.json"), reverse=True):
        doc = _read_document(path)
        if not doc:
            continue
        meta = doc.get("meta")
        if isinstance(meta, dict) and meta.get("job_id") == job_id:
            found.append(path)
    return found


def collect_feiliu_log_entries(
    job_id: str,
    *,
    settings: Settings,
    result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """返回该 job 的全部落盘日志（含完整 request/response，可直接转发给对方）。"""
    push_dir = settings.push_log_dir.resolve()
    seen: set[Path] = set()
    ordered: list[Path] = []

    for p in _paths_from_result(result):
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)

    for p in _scan_push_dir_for_job(push_dir, job_id):
        if p.resolve() not in seen:
            seen.add(p.resolve())
            ordered.append(p.resolve())

    entries: list[dict[str, Any]] = []
    for path in ordered:
        if not _is_under(path, push_dir):
            continue
        doc = _read_document(path)
        if doc is None:
            continue
        path_str = str(path)
        entries.append(
            {
                "path": path_str,
                "document_display": display_document(doc, log_path=path_str),
            }
        )
    return entries


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
