"""从现有大疆成片冻一小份 P1 抽帧，给后面改 prompt 对照用。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2

from uva.paths import DATA_DIR, EVAL_DIR

DEFAULT_TIMES_S = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]


def freeze_eval_set(video: Path | None = None, times_s: list[int] | None = None) -> dict:
    video_dir = DATA_DIR / "test_video"
    videos = sorted(video_dir.glob("*.mp4"))
    if video is None:
        if not videos:
            raise FileNotFoundError(video_dir)
        video = videos[0]
    times_s = times_s or DEFAULT_TIMES_S
    frames_dir = EVAL_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(video)
    items = []
    for t in times_s:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, bgr = cap.read()
        if not ok:
            continue
        h, w = bgr.shape[:2]
        if w > 1280:
            scale = 1280 / w
            bgr = cv2.resize(bgr, (1280, int(h * scale)))
        name = f"t{t:03d}s.jpg"
        path = frames_dir / name
        cv2.imwrite(str(path), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        items.append({"file": f"frames/{name}", "t_s": t, "source_video": video.name})
    cap.release()

    human = DATA_DIR / "test_img" / "30m-human.jpg"
    if human.is_file():
        dest = frames_dir / "still_30m_human.jpg"
        img = cv2.imread(str(human))
        if img is not None:
            cv2.imwrite(str(dest), img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            items.append({"file": "frames/still_30m_human.jpg", "t_s": None, "source_video": human.name})

    manifest = {
        "purpose": "P1 钓鱼人/游泳人 prompt 对照抽帧，不靠感觉改词。",
        "items": items,
    }
    (EVAL_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
