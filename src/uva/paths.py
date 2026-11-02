from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
PIPELINE_DIR = SRC_DIR / "pipeline"
DATA_DIR = PROJECT_ROOT / "data"
RUNTIME_DIR = DATA_DIR / "runtime"
EVAL_DIR = DATA_DIR / "eval_p1"
BIN_DIR = PROJECT_ROOT / "bin"
ENV_PATH = PROJECT_ROOT / ".env"


def ensure_src_on_path() -> None:
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)


def ensure_pipeline_importable() -> str:
    """让 `import config` / `from modules.x` 在任意工作目录可用。"""
    ensure_src_on_path()
    pipeline = str(PIPELINE_DIR)
    if pipeline not in sys.path:
        sys.path.insert(0, pipeline)
    return pipeline


def load_dotenv(path: Path | None = None) -> None:
    env_file = path or ENV_PATH
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
