"""成片遥测：外挂 SRT，或从 MP4 抽出 DJI 内嵌 tx3g 字幕。"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from uva.contract import Telemetry
from uva.ffmpeg_bin import find_ffmpeg
from uva.paths import ensure_pipeline_importable

logger = logging.getLogger(__name__)

_FIELD_KEYS = {"latitude", "longitude", "rel_alt", "osd_datetime"}


def sidecar_srt(video: Path) -> Path | None:
    seen: set[Path] = set()
    for suffix in (".srt", ".SRT"):
        cand = video.with_suffix(suffix)
        resolved = cand.resolve() if cand.exists() else cand
        if resolved in seen:
            continue
        seen.add(resolved)
        if cand.is_file():
            return cand
    return None


def extract_embedded_srt(video: Path, dest: Path) -> Path | None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        logger.warning("找不到 ffmpeg，无法从成片抽出内嵌字幕")
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(
        [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-map",
            "0:s:0",
            str(dest),
        ],
        **kwargs,
    )
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        if dest.is_file() and dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
        logger.warning("抽出内嵌字幕失败 video=%s stderr=%s", video.name, (proc.stderr or "").strip())
        return None
    return dest


def resolve_srt(video: Path, cache_dir: Path) -> Path | None:
    side = sidecar_srt(video)
    if side is not None:
        return side
    dest = cache_dir / f"{video.stem}.srt"
    try:
        if dest.is_file() and dest.stat().st_size > 0 and dest.stat().st_mtime >= video.stat().st_mtime:
            return dest
    except OSError:
        pass
    return extract_embedded_srt(video, dest)


def load_cues_for_video(video: Path, cache_dir: Path):
    srt = resolve_srt(video, cache_dir)
    if srt is None:
        return []
    ensure_pipeline_importable()
    from modules.subtitle_telemetry import parse_srt_file

    cues = parse_srt_file(str(srt))
    logger.info("成片字幕 cues=%s source=%s", len(cues), srt.name)
    return cues


def telemetry_from_fields(fields: dict[str, Any] | None, water_name: str | None = None) -> Telemetry:
    fields = dict(fields or {})
    lat, lon = _valid_coords(fields.get("latitude"), fields.get("longitude"))
    osd = fields.get("osd_datetime")
    captured = None
    if isinstance(osd, str) and osd.strip():
        captured = osd.strip().replace("T", " ").split(".")[0]
    extra = {k: v for k, v in fields.items() if k not in _FIELD_KEYS}
    return Telemetry(
        latitude=lat,
        longitude=lon,
        rel_alt=fields.get("rel_alt"),
        captured_at_local=captured,
        water_name=water_name,
        extra=extra,
    )


def telemetry_at_ms(cues, time_ms: float, water_name: str | None = None) -> Telemetry:
    if not cues:
        return Telemetry(water_name=water_name)
    ensure_pipeline_importable()
    from modules.subtitle_telemetry import lookup_cue_for_time_ms

    cue = lookup_cue_for_time_ms(cues, int(time_ms))
    if cue is None:
        return Telemetry(water_name=water_name)
    return telemetry_from_fields(cue.fields, water_name=water_name)


def _valid_coords(lat: Any, lon: Any) -> tuple[float | None, float | None]:
    if lat is None or lon is None:
        return None, None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None, None
    if abs(lat_f) < 1e-6 and abs(lon_f) < 1e-6:
        return None, None
    return lat_f, lon_f
