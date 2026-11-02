"""测试阶段：清空本机运行数据（队列、识别结果、帧图与证据图）。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from uva.settings import Settings
from uva.store import Store


def _clear_dir_contents(root: Path) -> int:
    if not root.is_dir():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
            removed += 1
        elif child.is_file():
            child.unlink(missing_ok=True)
            removed += 1
    return removed


def clear_local_test_data(settings: Settings, store: Store) -> dict[str, Any]:
    db_counts = store.purge_all()
    dirs = {
        "frames": settings.frames_dir,
        "evidence": settings.evidence_dir,
        "push_records": settings.push_log_dir,
    }
    dir_removed: dict[str, int] = {}
    for name, path in dirs.items():
        dir_removed[name] = _clear_dir_contents(path)
    return {
        "ok": True,
        "db_deleted": db_counts,
        "dirs_cleared": dir_removed,
        "note": "已清空本机测试运行数据；配置与模型权重未动。",
    }
