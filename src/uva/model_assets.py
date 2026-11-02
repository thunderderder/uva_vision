"""本地权重路径校验与按需从 Hugging Face 拉取（千问 VL 等）。"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_QWEN_VL_REPO = "Qwen/Qwen3-VL-2B-Instruct"


def qwen_dir_ready(model_dir: str | Path) -> bool:
    path = Path(model_dir)
    config = path / "config.json"
    if not config.is_file():
        return False
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(data.get("model_type"))


def ensure_qwen_vl_dir(
    model_dir: str | Path,
    *,
    repo_id: str = DEFAULT_QWEN_VL_REPO,
    allow_download: bool = True,
) -> Path:
    """确保 Qwen-VL 目录含有效 config.json；缺失时可从 HF 下载到该目录。"""
    path = Path(model_dir)
    if qwen_dir_ready(path):
        return path
    if not allow_download:
        raise FileNotFoundError(
            f"千问模型未就绪：{path}\n"
            f"目录缺少有效 config.json（model_type）。请执行：\n"
            f"  python -m uva download-qwen-vl"
        )
    path.mkdir(parents=True, exist_ok=True)
    # 清掉半截下载留下的空壳目录
    temp = path / "._____temp"
    if temp.is_dir() and not any(p for p in path.iterdir() if p.name != "._____temp"):
        import shutil

        shutil.rmtree(temp, ignore_errors=True)

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=repo_id,
        local_dir=str(path),
        local_dir_use_symlinks=False,
    )
    if not qwen_dir_ready(path):
        raise RuntimeError(f"下载完成但仍无法识别模型：{path}（repo={repo_id}）")
    return path
