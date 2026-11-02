from uva.rtmp import resolve_rtmp_endpoint
from uva.rtmp_url import redact_rtmp_url, uses_mtx_query_auth, with_rtmp_auth
from uva.settings import load_settings


def test_with_rtmp_auth_uses_query_for_mediamtx():
    out = with_rtmp_auth("rtmp://8.8.8.8:1935/live/uva", "pub", "s3cret")
    assert out == "rtmp://8.8.8.8:1935/live/uva?user=pub&pass=s3cret"


def test_with_rtmp_auth_keeps_existing_query_user():
    src = "rtmp://host:1935/live/uva?user=a&pass=b"
    assert with_rtmp_auth(src, "x", "y") == src


def test_with_rtmp_auth_converts_userinfo_to_query():
    src = "rtmp://a:b@host:1935/live/uva"
    assert with_rtmp_auth(src, "x", "y") == "rtmp://host:1935/live/uva?user=a&pass=b"


def test_with_rtmp_auth_empty_user_unchanged():
    src = "rtmp://127.0.0.1:1935/live/uva"
    assert with_rtmp_auth(src, "", "x") == src


def test_resolve_rtmp_endpoint_third_party_unchanged():
    settings = load_settings()
    settings.rtmp_user = "uva"
    settings.rtmp_password = "secret"
    ys7 = "rtmp://rtmp10open.ys7.com:1935/v3/openlive/x?expire=1&t=x"
    assert resolve_rtmp_endpoint(ys7, settings) == ys7
    local = resolve_rtmp_endpoint("rtmp://127.0.0.1:1935/live/uva", settings)
    assert local == "rtmp://127.0.0.1:1935/live/uva?user=uva&pass=secret"


def test_uses_mtx_query_auth_local_and_env_hosts():
    ecs = frozenset({"8.8.8.8"})
    assert uses_mtx_query_auth("rtmp://127.0.0.1:1935/live/uva", ecs)
    assert uses_mtx_query_auth("rtmp://8.8.8.8:1935/live/uva", ecs)
    assert not uses_mtx_query_auth(
        "rtmp://rtmp10open.ys7.com:1935/v3/openlive/x?expire=1&t=x",
        ecs,
    )


def test_redact_rtmp_url_hides_pass():
    red = redact_rtmp_url("rtmp://h:1935/live/uva?user=u&pass=secret")
    assert "secret" not in red
    assert "live/uva" in red
    assert "user=u" in red
