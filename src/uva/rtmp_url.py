"""RTMP URL 拼装：账号只从环境变量来，不写进代码。

MediaMTX 的 RTMP 鉴权走 query（user/pass），不是 user:pass@host。
后者会让 FFmpeg 走 Adobe 握手，对 MediaMTX 表现为 handshake EOF。
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_LOCAL_MTX_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _hostport(parsed) -> str:
    host = parsed.hostname or ""
    if parsed.port:
        return f"{host}:{parsed.port}"
    return host


def uses_mtx_query_auth(url: str, mtx_hosts: frozenset[str] | set[str]) -> bool:
    """是否应对该 URL 追加 MediaMTX 的 ?user=&pass=（第三方 openlive 等应返回 False）。"""
    url = (url or "").strip()
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    if host in _LOCAL_MTX_HOSTS:
        return True
    return host in mtx_hosts


def with_rtmp_auth(url: str, user: str = "", password: str = "") -> str:
    """把 user/pass 填成 MediaMTX 认识的 ?user=&pass=。已有 query user 的地址原样返回。"""
    url = (url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query.get("user"):
        return url
    user = parsed.username or user
    password = parsed.password if parsed.password is not None else password
    if not user:
        return url
    query["user"] = user
    if password:
        query["pass"] = password
    return urlunparse((parsed.scheme, _hostport(parsed), parsed.path, parsed.params, urlencode(query), parsed.fragment))


def redact_rtmp_url(url: str) -> str:
    """日志用，去掉密码。"""
    url = (url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("pass", "password", "pwd"):
        if key in query and query[key]:
            query[key] = "***"
    return urlunparse(
        (parsed.scheme, _hostport(parsed), parsed.path, parsed.params, urlencode(query), parsed.fragment)
    )
