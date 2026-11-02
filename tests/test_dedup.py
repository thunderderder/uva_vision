import time
from pathlib import Path

from uva.dedup import bucket_key, should_skip
from uva.store import Store


def test_cooldown_skips_then_expires(tmp_path: Path):
    store = Store(tmp_path / "uva.sqlite3")
    bucket = bucket_key("person", [0, 0, 100, 100], grid=160)
    now = time.time()
    store.touch_dedup(bucket, now, "job_1", None)
    assert should_skip(store, bucket, now + 10, cooldown_s=120)
    assert not should_skip(store, bucket, now + 200, cooldown_s=120)
