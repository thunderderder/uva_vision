"""Job / Result JSON 合同。这是 ingest 与 GPU worker 之间的迁移接口。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Literal

SCHEMA_VERSION = "1"

SourceType = Literal["rtmp", "file"]
JobStatus = Literal["queued", "running", "done", "failed", "ims_retry"]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:16]
    return f"{prefix}{token}" if prefix else token


@dataclass
class Telemetry:
    latitude: float | None = None
    longitude: float | None = None
    water_name: str | None = None
    captured_at_local: str | None = None
    rel_alt: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra") or {}
        data.update(extra)
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Telemetry":
        data = dict(data or {})
        known = {f.name for f in fields(cls)} - {"extra"}
        kwargs = {k: data.pop(k) for k in list(data) if k in known}
        return cls(**kwargs, extra=data)


@dataclass
class Job:
    job_id: str
    run_id: str
    source_type: SourceType
    media_path: str
    captured_at: str
    schema_version: str = SCHEMA_VERSION
    stream_key: str | None = None
    frame_index: int | None = None
    telemetry: Telemetry = field(default_factory=Telemetry)
    water_name: str | None = None
    status: JobStatus = "queued"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "run_id": self.run_id,
            "source_type": self.source_type,
            "media_path": self.media_path,
            "captured_at": self.captured_at,
            "stream_key": self.stream_key,
            "frame_index": self.frame_index,
            "telemetry": self.telemetry.to_dict(),
            "water_name": self.water_name or self.telemetry.water_name,
            "status": self.status,
            "created_at": self.created_at,
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        payload = dict(data)
        telemetry = Telemetry.from_dict(payload.pop("telemetry", None))
        payload.pop("schema_version", None)
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in payload.items() if k in known}
        kwargs.setdefault("job_id", new_id("job_"))
        kwargs.setdefault("run_id", new_id("run_"))
        kwargs.setdefault("captured_at", utc_now())
        kwargs.setdefault("media_path", "")
        kwargs.setdefault("source_type", "file")
        return cls(telemetry=telemetry, **kwargs)

    @classmethod
    def from_json(cls, text: str) -> "Job":
        return cls.from_dict(json.loads(text))


@dataclass
class FrameResult:
    job_id: str | None
    run_id: str | None
    detections: list[dict[str, Any]]
    qwen_results: list[dict[str, Any]]
    alarms: list[dict[str, Any]]
    confirmed_alerts: list[dict[str, Any]]
    skipped_reason: str | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    ims_push: dict[str, Any] | None = None
    feiliu_push: dict[str, Any] | None = None
    scene_descriptions: list[str] = field(default_factory=list)
    status: str = "ok"
    vlm_layout: str | None = None
    yolo_ms: int | None = None
    vlm_ms: int | None = None
    yolo_detect_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
