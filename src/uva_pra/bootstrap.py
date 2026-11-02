from __future__ import annotations

import sys
from pathlib import Path

# Monorepo: uva (kernel) + uva_pra (workbench) share one project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRA_ROOT = PROJECT_ROOT
UVA_ROOT = PROJECT_ROOT


def ensure_uva_paths() -> None:
    """Load src + pipeline on sys.path and project .env (same layout as `python -m uva`)."""
    uva_src = UVA_ROOT / "src"
    if uva_src.is_dir():
        src = str(uva_src)
        if src not in sys.path:
            sys.path.insert(0, src)
    from uva.paths import ensure_pipeline_importable, load_dotenv

    load_dotenv(UVA_ROOT / ".env")
    ensure_pipeline_importable()
