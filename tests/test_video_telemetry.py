from pathlib import Path

import cv2
import numpy as np

from uva.ingest import ingest_path
from uva.settings import load_settings
from uva.video_telemetry import load_cues_for_video, telemetry_at_ms, telemetry_from_fields

DJI_SRT = """1
00:00:00,000 --> 00:00:00,033
FrameCnt: 0 2026-05-07 17:03:08.233
[iso: 190] [shutter: 1/320.0] [fnum: 2.8] [ev: 0] [color_md: default] [ae_meter_md: 1] [focal_len: 81.20] [dzoom_ratio: 1.16], [latitude: 31.230416] [longitude: 121.473701] [rel_alt: 119.984 abs_alt: 170.174] [gb_yaw: -98.8 gb_pitch: -58.6 gb_roll: 0.0] [dehaze_level: 0] [dehaze_mode: 0]

2
00:00:02,000 --> 00:00:02,033
FrameCnt: 60 2026-05-07 17:03:10.200
[latitude: 31.230420] [longitude: 121.473710] [rel_alt: 120.100]
"""


def test_parse_dji_osd_line():
    from uva.paths import ensure_pipeline_importable

    ensure_pipeline_importable()
    from modules.subtitle_telemetry import parse_osd_text, parse_srt_text

    fields = parse_osd_text(DJI_SRT.split("FrameCnt", 1)[1])
    assert fields["latitude"] == 31.230416
    assert fields["longitude"] == 121.473701
    assert fields["rel_alt"] == 119.984
    assert fields["osd_datetime"].startswith("2026-05-07 17:03:08")
    cues = parse_srt_text(DJI_SRT)
    assert len(cues) == 2
    tele = telemetry_at_ms(cues, 0)
    assert tele.latitude == 31.230416
    assert tele.longitude == 121.473701
    assert tele.captured_at_local == "2026-05-07 17:03:08"
    later = telemetry_at_ms(cues, 2000)
    assert later.latitude == 31.230420


def test_zero_gps_dropped():
    tele = telemetry_from_fields({"latitude": 0.0, "longitude": 0.0})
    assert tele.latitude is None
    assert tele.longitude is None


def test_sidecar_srt_preferred(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not-a-real-video")
    (tmp_path / "clip.srt").write_text(DJI_SRT, encoding="utf-8")
    monkeypatch.setattr("uva.video_telemetry.extract_embedded_srt", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should use sidecar")))
    cues = load_cues_for_video(video, tmp_path / "cache")
    assert cues[0].fields["latitude"] == 31.230416


def test_embedded_srt_extracted(tmp_path, monkeypatch):
    video = tmp_path / "air.mp4"
    video.write_bytes(b"fake")

    def fake_extract(src, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(DJI_SRT, encoding="utf-8")
        return dest

    monkeypatch.setattr("uva.video_telemetry.extract_embedded_srt", fake_extract)
    cues = load_cues_for_video(video, tmp_path / "subs")
    tele = telemetry_at_ms(cues, 10)
    assert tele.longitude == 121.473701


def _tiny_mp4(path: Path, n: int = 6, fps: float = 5.0) -> bool:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (32, 32))
    if not writer.isOpened():
        return False
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    for _ in range(n):
        writer.write(frame)
    writer.release()
    return path.is_file()


def test_ingest_video_attaches_sidecar_gps(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    if not _tiny_mp4(video):
        return
    (tmp_path / "clip.srt").write_text(DJI_SRT, encoding="utf-8")
    settings = load_settings()
    settings.runtime_dir = tmp_path / "rt"
    settings.frames_dir = settings.runtime_dir / "frames"
    settings.db_path = settings.runtime_dir / "uva.sqlite3"
    settings.frame_interval_s = 0.5
    monkeypatch.setenv("UVA_RUNTIME_DIR", str(settings.runtime_dir))
    run_id, jobs = ingest_path(video, run_id="run_gps", settings=settings)
    assert run_id == "run_gps"
    assert jobs
    assert jobs[0].telemetry.latitude == 31.230416
    assert jobs[0].telemetry.longitude == 121.473701
    assert jobs[0].captured_at == "2026-05-07 17:03:08"
