"""Pytest bootstrap: src + pipeline on sys.path."""

from __future__ import annotations

from uva.paths import ensure_pipeline_importable, ensure_src_on_path

ensure_src_on_path()
ensure_pipeline_importable()
