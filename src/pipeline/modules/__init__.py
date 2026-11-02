"""推理子模块；缺失 .py 时从同目录 __pycache__ 加载匹配的 .pyc。"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_CACHE = _PKG_DIR / "__pycache__"
_TAG = f"cpython-{sys.version_info.major}{sys.version_info.minor}"


class _ModulesPycFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path, target=None):  # noqa: ANN001
        if not fullname.startswith("modules.") or fullname.count(".") != 1:
            return None
        short = fullname.split(".", 1)[1]
        if (_PKG_DIR / f"{short}.py").is_file():
            return None
        matches = sorted(_CACHE.glob(f"{short}.{_TAG}*.pyc"), reverse=True)
        if not matches:
            return None
        loader = importlib.machinery.SourcelessFileLoader(fullname, str(matches[0]))
        return importlib.util.spec_from_loader(fullname, loader)


if not any(isinstance(finder, _ModulesPycFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _ModulesPycFinder())
