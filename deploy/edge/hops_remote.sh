#!/usr/bin/env bash
# GPU 机器 hops 经 SSH 调用。stdout 只有 JSON，日志里的 pass= 会打码。
set -euo pipefail
python3 - <<'PY'
import json, re, subprocess, urllib.request

def sh(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT, timeout=8)
    except Exception as e:
        return str(e)

def curl_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}

def mem_mb() -> int:
    try:
        for line in open("/proc/meminfo", encoding="ascii"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except Exception:
        return 0
    return 0

journal = sh("journalctl -u uva-edge.service -n 40 --no-pager -o cat")
journal = re.sub(r"(pass|password|pwd)=[^ \n&]+", r"\1=***", journal, flags=re.I)

print(json.dumps({
    "service": sh("systemctl is-active uva-edge.service").strip(),
    "listen_1935": ":1935" in sh("ss -lnt"),
    "nproc": sh("nproc").strip(),
    "mem_mb": mem_mb(),
    "paths": curl_json("http://127.0.0.1:9997/v3/paths/list"),
    "rtmp_conns": curl_json("http://127.0.0.1:9997/v3/rtmpconns/list"),
    "journal_tail": journal[-3000:],
}, ensure_ascii=False))
PY
