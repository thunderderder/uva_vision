from __future__ import annotations

import csv
import io
import json
from typing import Any

from uva.audit_view import build_run_detail
from uva.store import Store


def build_run_export(store: Store, run_id: str) -> dict[str, Any]:
    detail = build_run_detail(store, run_id)
    jobs = detail.get("jobs") or []
    alert_jobs = 0
    push_ok = 0
    for job in jobs:
        outcome = job.get("outcome") or ""
        if "预警" in outcome:
            alert_jobs += 1
        if job.get("ims_chip_tone") == "ok" or (job.get("ims_label") or "").startswith("已推 IMS"):
            push_ok += 1
    return {
        "run": detail.get("run"),
        "summary": {
            "job_count": len(jobs),
            "alert_frames": alert_jobs,
            "ims_pushed_frames": push_ok,
        },
        "jobs": [
            {
                "job_id": j.get("job_id"),
                "title": j.get("title"),
                "outcome": j.get("outcome"),
                "ims_label": j.get("ims_label"),
                "feiliu_label": j.get("feiliu_label"),
                "image_path": j.get("image_path"),
            }
            for j in jobs
        ],
    }


def export_csv(store: Store, run_id: str) -> str:
    data = build_run_export(store, run_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["job_id", "title", "outcome", "ims_label", "feiliu_label", "image_path"])
    for row in data["jobs"]:
        writer.writerow(
            [
                row["job_id"],
                row["title"],
                row["outcome"],
                row["ims_label"],
                row.get("feiliu_label"),
                row["image_path"],
            ]
        )
    return buf.getvalue()
