from pathlib import Path

import cv2
import numpy as np

from uva.ingest import ingest_folder, ingest_path
from uva.settings import load_settings


def test_ingest_image_enqueues(tmp_path, monkeypatch):
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    src = tmp_path / "one.jpg"
    cv2.imwrite(str(src), img)
    settings = load_settings()
    settings.runtime_dir = tmp_path / "rt"
    settings.frames_dir = settings.runtime_dir / "frames"
    settings.db_path = settings.runtime_dir / "uva.sqlite3"
    monkeypatch.setenv("UVA_RUNTIME_DIR", str(settings.runtime_dir))
    run_id, jobs = ingest_path(src, run_id="run_test", settings=settings)
    assert run_id == "run_test"
    assert len(jobs) == 1
    assert Path(jobs[0].media_path).is_file()
    assert jobs[0].source_type == "file"


def test_ingest_folder_enqueues_sorted(tmp_path, monkeypatch):
    settings = load_settings()
    settings.runtime_dir = tmp_path / "rt"
    settings.frames_dir = settings.runtime_dir / "frames"
    settings.db_path = settings.runtime_dir / "uva.sqlite3"
    monkeypatch.setenv("UVA_RUNTIME_DIR", str(settings.runtime_dir))
    folder = tmp_path / "shots"
    folder.mkdir()
    for name in ("b.jpg", "a.jpg"):
        img = np.zeros((16, 16, 3), dtype=np.uint8)
        cv2.imwrite(str(folder / name), img)
    run_id, jobs = ingest_folder(folder, run_id="run_folder", settings=settings, recursive=False)
    assert run_id == "run_folder"
    assert len(jobs) == 2
    assert jobs[0].frame_index == 0
    assert "folder_000000__a.jpg" in jobs[0].media_path
