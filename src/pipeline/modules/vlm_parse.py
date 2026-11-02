"""解析 Qwen 复核原文。不依赖模型，供 verifier 与测试共用。"""

from __future__ import annotations

import re
from typing import Any

_ID_TYPE = re.compile(
    r"(?i)ID:\s*\[?(\d+)\]?\s*,\s*Type:\s*([^,\n]+?)(?:\s*,\s*Description:\s*(.*))?$"
)


def parse_vlm_output(text: str) -> dict[str, Any]:
    """把多段 ID/Type/Description 收成按编号对齐的结构。"""
    verified: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _ID_TYPE.match(line)
        if match:
            current = {
                "id": int(match.group(1)),
                "type": match.group(2).strip(),
                "description": (match.group(3) or "").strip(),
            }
            verified.append(current)
            continue
        if line.lower().startswith("description:") and current is not None:
            current["description"] = line.split(":", 1)[1].strip()
            continue
        if current is not None and current.get("description") and line:
            current["description"] = f"{current['description']} {line}"

    last_desc = ""
    for item in reversed(verified):
        if item.get("description"):
            last_desc = item["description"]
            break
    return {
        "verified_objects": verified,
        "description": last_desc,
        "raw_text": text,
    }
