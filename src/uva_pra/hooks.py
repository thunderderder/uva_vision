from __future__ import annotations

from typing import Any

from uva.contract import Job
from uva.settings import Settings
from uva.store import Store

from uva_pra.feiliu import push_alert


def feiliu_after_alert(
    *,
    job: Job,
    alert: dict[str, Any],
    evidence: dict[str, str],
    store: Store,
    settings: Settings,
) -> dict[str, Any] | None:
    return push_alert(job=job, alert=alert, evidence=evidence, store=store, settings=settings)
