"""定位本机 ffmpeg。WinGet Gyan.FFmpeg 不在 PATH 时也能找到。"""

from __future__ import annotations

import shutil
from pathlib import Path

from uva.paths import BIN_DIR

FFMPEG_HINT = "winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements"


def find_ffmpeg() -> Path | None:
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    local = BIN_DIR / "ffmpeg.exe"
    if local.is_file():
        return local
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    hits = sorted(winget.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"))
    return hits[-1] if hits else None


def ensure_ffmpeg() -> Path:
    exe = find_ffmpeg()
    if exe is None:
        raise FileNotFoundError(f"找不到 ffmpeg。在本机安装后重试：{FFMPEG_HINT}")
    return exe
