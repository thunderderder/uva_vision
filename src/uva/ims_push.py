"""巡查结果表 fieldQueryList 拼装与推送。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from uva.contract import Job
from uva.p1 import DISPATCH_NO, ISSUE_CODE, SOURCE_FILE, SOURCE_RTMP, VERIFY_PENDING
from uva.settings import Settings

logger = logging.getLogger(__name__)

FIELDS = {
    "source": {"cId": "1957719986525048832", "cType": 4},
    "verify": {"cId": "2095414411492724736", "cType": 6},
    "ai_type": {"cId": "1948398814431940608", "cType": 1},
    "result": {"cId": "1947836187691585537", "cType": 1},
    "shot_time": {"cId": "1948401451038543872", "cType": 1},
    "location": {"cId": "1947836187691585539", "cType": 1},
    "det_img": {"cId": "1947836187691585540", "cType": 10},
    "raw_img": {"cId": "1947836187691585541", "cType": 10},
    "issue": {"cId": "1947837535187243008", "cType": 7},
    "lon": {"cId": "1957377849216339968", "cType": 1},
    "lat": {"cId": "1957377849216339969", "cType": 1},
    "dispatch": {"cId": "1957712850235559936", "cType": 6},
    "idem": {"cId": "2095418085577199616", "cType": 1},
    "run_id": {"cId": "2095418085577199617", "cType": 1},
}

IDEMPOTENCY_CID = FIELDS["idem"]["cId"]


def _item(name: str, value: Any) -> dict[str, Any]:
    spec = FIELDS[name]
    return {"key": spec["cId"], "value": value, "type": spec["cType"]}


def source_code(source_type: str) -> int:
    return SOURCE_RTMP if source_type == "rtmp" else SOURCE_FILE


def build_field_query_list(
    *,
    job: Job,
    alert: dict[str, Any],
    idempotency_key: str,
    detected_url: str | None,
    original_url: str | None,
    water_name: str | None = None,
) -> list[dict[str, Any]]:
    alert_type = alert.get("alert_type")
    ims_type = alert.get("ims_type") or ""
    description = alert.get("description") or ims_type
    tele = job.telemetry
    items = [
        _item("source", source_code(job.source_type)),
        _item("verify", VERIFY_PENDING),
        _item("ai_type", ims_type),
        _item("result", description),
        _item("shot_time", job.captured_at.replace("T", " ").replace("Z", "")),
        _item("issue", ISSUE_CODE.get(alert_type, "")),
        _item("dispatch", DISPATCH_NO),
        _item("idem", idempotency_key),
        _item("run_id", job.run_id),
    ]
    loc = water_name or job.water_name or tele.water_name
    if loc:
        items.append(_item("location", loc))
    if tele.longitude is not None:
        items.append(_item("lon", str(tele.longitude)))
    if tele.latitude is not None:
        items.append(_item("lat", str(tele.latitude)))
    if detected_url:
        items.append(_item("det_img", detected_url.split("?")[0]))
    if original_url:
        items.append(_item("raw_img", original_url.split("?")[0]))
    return [item for item in items if item["value"] not in ("", None)]


def write_push_record(directory: Path, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"push_{int(time.time() * 1000)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def add_url(settings: Settings) -> str:
    return f"{settings.data_api_auth_url}{settings.ims_add_path}"
