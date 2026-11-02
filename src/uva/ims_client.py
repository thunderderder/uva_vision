"""IMS 登录、OSS 上传、Bearer 请求。不把图回填到 zj_resultImg。"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests
import urllib3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

urllib3.disable_warnings()

logger = logging.getLogger(__name__)


class IMSClient:
    def __init__(
        self,
        auth_url: str,
        username: str,
        password: str,
        aes_key: str,
        oss_ak: str,
        oss_sk: str,
        oss_endpoint: str,
        oss_bucket: str,
        env_path: str | Path = ".env",
        verify_ssl: bool = False,
    ):
        self.auth_url = auth_url.rstrip("/")
        self.username = username
        self.password = password
        self.aes_key = aes_key
        self.oss_ak = oss_ak
        self.oss_sk = oss_sk
        self.oss_endpoint = oss_endpoint
        self.oss_bucket = oss_bucket
        self.env_path = str(env_path)
        self.verify_ssl = verify_ssl
        self.current_token = self._load_token_from_env()
        self.split_key = "#&&#"

    def _load_token_from_env(self) -> str:
        if not os.path.exists(self.env_path):
            return os.environ.get("DATA_API_TOKEN", "")
        text = Path(self.env_path).read_text(encoding="utf-8", errors="replace")
        match = re.search(r"DATA_API_TOKEN=(.*)", text)
        return match.group(1).strip() if match else os.environ.get("DATA_API_TOKEN", "")

    def _update_env_file(self, new_token: str) -> None:
        path = Path(self.env_path)
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8", errors="replace")
        pattern = r"DATA_API_TOKEN=(.*)"
        replacement = f"DATA_API_TOKEN={new_token}"
        new_content = re.sub(pattern, replacement, content) if re.search(pattern, content) else f"{content}\n{replacement}\n"
        path.write_text(new_content, encoding="utf-8")

    def _aes_encrypt(self, content: str) -> str:
        key = self.aes_key.encode("utf-8")
        if len(key) not in (16, 24, 32):
            key = key[:16].ljust(16, b"\0")
        cipher = AES.new(key, AES.MODE_ECB)
        padded = pad(content.encode("utf-8"), AES.block_size)
        return base64.b64encode(cipher.encrypt(padded)).decode("utf-8")

    def _refresh_token(self) -> bool:
        logger.info("刷新 IMS DATA_API token")
        try:
            seed = requests.post(
                f"{self.auth_url}/api/getEncryptKey",
                timeout=15,
                verify=self.verify_ssl,
            )
            body = seed.json()
            if body.get("code") != 200:
                logger.error("getEncryptKey 失败: %s", body)
                return False
            encrypted = self._aes_encrypt(self.password + self.split_key + body["data"])
            login = requests.post(
                f"{self.auth_url}/api/login",
                json={"username": self.username, "password": encrypted},
                timeout=15,
                verify=self.verify_ssl,
            )
            login_body = login.json()
            if login_body.get("code") == 200:
                token_data = login_body["data"]
                self.current_token = f"{token_data['tokenHead']} {token_data['token']}"
                self._update_env_file(self.current_token)
                return True
            logger.error("login 失败: %s", login_body)
        except Exception:
            logger.exception("IMS 登录异常")
        return False

    def upload_file(self, local_file_path: str, oss_key: str | None = None) -> Optional[str]:
        import oss2

        if not os.path.exists(local_file_path):
            logger.error("待上传文件不存在: %s", local_file_path)
            return None
        auth = oss2.Auth(self.oss_ak, self.oss_sk)
        bucket = oss2.Bucket(auth, self.oss_endpoint, self.oss_bucket)
        ext = local_file_path.lower().rsplit(".", 1)[-1]
        content_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png" if ext == "png" else "application/octet-stream"
        filename = os.path.basename(local_file_path)
        oss_key = oss_key or f"ims/sys/uva/{int(time.time() * 1000)}_{filename}"
        result = bucket.put_object_from_file(oss_key, local_file_path, headers={"Content-Type": content_type})
        if result.status == 200:
            endpoint_clean = self.oss_endpoint.replace("https://", "").replace("http://", "")
            return f"https://{self.oss_bucket}.{endpoint_clean}/{oss_key}"
        logger.error("OSS 上传失败 status=%s", result.status)
        return None

    def request_json(self, method: str, url: str, **kwargs) -> Optional[Any]:
        if not self.current_token and not self._refresh_token():
            return None
        headers = kwargs.pop("headers", {})
        headers["Content-Type"] = "application/json;charset=UTF-8"
        headers["Authorization"] = (
            self.current_token if self.current_token.startswith("Bearer ") else f"Bearer {self.current_token}"
        )
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", 30)
        kwargs.setdefault("verify", self.verify_ssl)
        try:
            response = requests.request(method, url, **kwargs)
            resp_json = response.json() if response.content else {}
            if response.status_code == 401 or (isinstance(resp_json, dict) and resp_json.get("code") == 401):
                if not self._refresh_token():
                    return None
                headers["Authorization"] = self.current_token
                response = requests.request(method, url, **kwargs)
                resp_json = response.json() if response.content else {}
            if response.status_code != 200:
                logger.error("IMS HTTP %s %s %s", response.status_code, url, str(resp_json)[:300])
            return resp_json
        except requests.RequestException:
            logger.exception("IMS 网络失败 %s", url)
            return None

    def add_row(self, url: str, field_query_list: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        return self.request_json("POST", url, json={"fieldQueryList": field_query_list})

    def page_by_idempotency(self, form_id: str, field_cid: str, value: str) -> list[dict[str, Any]]:
        url = f"{self.auth_url}/form/result/page/{form_id}"
        body = {
            "pageNum": 1,
            "pageSize": 5,
            "fieldQueryList": [{"key": field_cid, "type": 0, "value": value}],
        }
        res = self.request_json("POST", url, json=body)
        if not isinstance(res, dict):
            return []
        data = res.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            records = data.get("records") or data.get("list") or data.get("rows") or []
            return records if isinstance(records, list) else []
        return []
