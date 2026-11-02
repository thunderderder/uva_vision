"""本地视频元数据（不依赖 ffmpeg 解析时长）。"""

from __future__ import annotations

from pathlib import Path


def video_duration_sec(path: Path) -> float:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"打不开视频: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    if fps <= 0 or frames <= 0:
        return 0.0
    return frames / fps
