"""DJI / 成片 SRT 字幕解析，供 GPS 与 OSD 时间对齐。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_BRACKET = re.compile(r"\[([^:\]]+):\s*([^\]]+)\]")
_TIMECODE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)
_FRAME_OSD = re.compile(r"FrameCnt:\s*\d+\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


@dataclass
class SubtitleCue:
    start_ms: int
    end_ms: int
    fields: dict[str, Any]


def _tc_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)


def parse_osd_text(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, raw in _BRACKET.findall(text):
        key = key.strip()
        val = raw.strip()
        if key == "latitude":
            if "latitude" not in fields:
                fields["latitude"] = float(val.split()[0])
        elif key == "longitude":
            if "longitude" not in fields:
                fields["longitude"] = float(val.split()[0])
        elif key == "rel_alt":
            if "rel_alt" not in fields:
                fields["rel_alt"] = float(val.split()[0])
        elif key not in fields:
            fields[key] = val
    if "osd_datetime" not in fields:
        stamp = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", text)
        if stamp:
            fields["osd_datetime"] = stamp.group(1)
        else:
            osd = _FRAME_OSD.search(text)
            if osd:
                fields["osd_datetime"] = osd.group(1)
    return fields


def parse_srt_text(text: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        idx = 1 if lines[0].isdigit() else 0
        if idx >= len(lines):
            continue
        match = _TIMECODE.search(lines[idx])
        if not match:
            continue
        start_ms = _tc_to_ms(*match.groups()[0:4])
        end_ms = _tc_to_ms(*match.groups()[4:8])
        body = "\n".join(lines[idx + 1 :])
        fields = parse_osd_text(body) if body else {}
        cues.append(SubtitleCue(start_ms=start_ms, end_ms=end_ms, fields=fields))
    return cues


def parse_srt_file(path: str) -> list[SubtitleCue]:
    return parse_srt_text(Path(path).read_text(encoding="utf-8", errors="replace"))


def lookup_cue_for_time_ms(cues: list[SubtitleCue], time_ms: int) -> SubtitleCue | None:
    if not cues:
        return None
    hit: SubtitleCue | None = None
    for cue in cues:
        if cue.start_ms <= time_ms <= cue.end_ms:
            return cue
        if cue.start_ms <= time_ms:
            hit = cue
    return hit
