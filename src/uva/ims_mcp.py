"""IMS MCP 写入：预签名直传 OSS + 巡查结果新增。

这是 worker 里的固定 HTTP 调用，不是模型选工具。握手一次，每条预警重复预签名 / PUT / addrow。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote

logger = logging.getLogger(__name__)

DEFAULT_MCP_URL = "https://api.example.com/ims/mcp/"
PRESIGN_TOOL = "GetApiV2FileGetuploadpresignurlSysBySystemid"
ADDROW_TOOL = "PostApiV2FormResultAddrow"


class ImsMcpError(RuntimeError):
    pass


def parse_mcp_tool_text(text: str) -> Any:
    """MCP 网关把 IMS 结果包在 `API Response` 文本里；预签名接口经常是裸 URL。"""
    if text.startswith("Invalid arguments"):
        raise ImsMcpError(text)
    body = text.split("\n", 1)[1].strip() if text.startswith("API Response") and "\n" in text else text
    body = body.strip().strip('"')
    if not body:
        return None
    if body.startswith("{") or body.startswith("["):
        return json.loads(body)
    return body


def extract_presign_url(res: Any) -> str:
    if isinstance(res, str):
        text = res.strip().strip('"')
        if text.startswith("http"):
            return text
    if isinstance(res, dict):
        data = res.get("data", res)
        if isinstance(data, str) and data.startswith("http"):
            return data
        if isinstance(data, dict):
            for key in ("url", "uploadUrl", "signedUrl", "presignUrl"):
                val = data.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    return val
        msg = res.get("message")
        if isinstance(msg, str) and msg.startswith("http"):
            return msg
    raise ImsMcpError(f"预签名返回无法解析: {str(res)[:240]}")


def clean_oss_url(upload_url: str) -> str:
    return unquote(upload_url.split("?")[0])


def to_mcp_controls(field_query_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"ctrlId": row["key"], "value": row["value"]} for row in field_query_list]


def addrow_ok(res: Any) -> bool:
    if isinstance(res, dict):
        return res.get("code") in (200, "200", 0)
    return False


def put_object(upload_url: str, local_path: Path, content_type: str = "image/jpeg", timeout: float = 120.0) -> int:
    """直传 OSS。不要带 Authorization，否则预签名会 403。"""
    body = Path(local_path).read_bytes()
    req = urllib.request.Request(upload_url, data=body, method="PUT")
    req.add_header("X-Oss-Object-Acl", "private")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        logger.error("OSS PUT HTTP %s %s", exc.code, detail)
        return int(exc.code)


class ImsMcpWriter:
    def __init__(
        self,
        *,
        url: str,
        secret: str,
        sys_id: str,
        form_id: str,
        timeout: float = 60.0,
        put_fn: Callable[[str, Path, str], int] | None = None,
    ) -> None:
        self.url = (url or DEFAULT_MCP_URL).rstrip("/") + "/"
        self.secret = secret
        self.sys_id = sys_id
        self.form_id = form_id
        self.timeout = timeout
        self._session: Optional[str] = None
        self._put_fn = put_fn or (lambda u, p, ct: put_object(u, p, ct))
        if not self.secret:
            raise ImsMcpError("缺少 IMS_MCP_SECRET")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "x-mcp-secret": self.secret,
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        return headers

    @staticmethod
    def _parse_sse(text: str) -> Any:
        if not text.strip():
            return None
        for line in text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
        return json.loads(text)

    def _post(self, body: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if sid := resp.headers.get("mcp-session-id"):
                    self._session = sid
                return self._parse_sse(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ImsMcpError(f"MCP HTTP {exc.code}: {detail}") from exc

    def ensure_session(self) -> None:
        if self._session:
            return
        init = self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "uva-ims-mcp", "version": "1.0"},
                },
            }
        )
        if not init or "error" in init:
            raise ImsMcpError(f"MCP initialize 失败: {init}")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> Any:
        self.ensure_session()
        payload = self._post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        if not payload or "error" in payload:
            raise ImsMcpError(f"tools/call 失败: {payload}")
        content = (payload.get("result") or {}).get("content") or []
        if not content:
            return None
        text = content[0].get("text", "")
        return parse_mcp_tool_text(text)

    def upload_file(self, local_path: str | Path, file_name: str) -> str:
        path = Path(local_path)
        if not path.is_file():
            raise ImsMcpError(f"证据文件不存在: {path}")
        pres = self.call_tool(PRESIGN_TOOL, {"systemId": self.sys_id, "fileName": file_name})
        upload_url = extract_presign_url(pres)
        status = self._put_fn(upload_url, path, "image/jpeg")
        if status not in (200, 201, 204):
            raise ImsMcpError(f"OSS PUT 失败 status={status} file={file_name}")
        return clean_oss_url(upload_url)

    def add_row(self, controls: list[dict[str, Any]]) -> Any:
        return self.call_tool(
            ADDROW_TOOL,
            {"sysId": self.sys_id, "formId": self.form_id, "controls": controls},
        )
