#!/usr/bin/env bash
# 在任意 Linux 上安装收流节点。无 GPU、不装 Python 模型。
# 用法：
#   sudo PUBLIC_HOST=x.x.x.x ./install_edge.sh
# PUBLIC_HOST 写入本机 GPU 的 UVA_RTMP_PULL_URL / PUBLISH_URL。不填则尝试探测公网 IP。
set -euo pipefail

VER="${MEDIAMTX_VERSION:-v1.20.1}"
DIR="${UVA_EDGE_DIR:-/opt/uva-edge}"
USER_NAME="${UVA_RTMP_USER:-uva}"
PASS_WORD="${UVA_RTMP_PASSWORD:-}"
PUBLIC_HOST="${PUBLIC_HOST:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行" >&2
  exit 1
fi

if [[ -z "$PUBLIC_HOST" ]]; then
  PUBLIC_HOST="$(curl -4 -fsS --max-time 5 https://ifconfig.me || true)"
fi
if [[ -z "$PUBLIC_HOST" ]]; then
  echo "请设置 PUBLIC_HOST=收流公网IP或域名" >&2
  exit 1
fi

# 国内 ECS 经常拉不下 GitHub：优先用脚本旁的 tar.gz，或 MEDIAMTX_TGZ。
LOCAL_TGZ="${MEDIAMTX_TGZ:-}"
if [[ -z "$LOCAL_TGZ" ]]; then
  for candidate in \
    "$SCRIPT_DIR/mediamtx_${VER}_linux_amd64.tar.gz" \
    "$SCRIPT_DIR/mediamtx_linux_amd64.tar.gz"; do
    if [[ -f "$candidate" ]]; then
      LOCAL_TGZ="$candidate"
      break
    fi
  done
fi

mkdir -p "$DIR"

# 重装时沿用已有账号，避免 GPU 机器 .env 失效。
if [[ -z "$PASS_WORD" && -f "$DIR/gpu.env.snippet" ]]; then
  existing="$(awk -F= '/^UVA_RTMP_PASSWORD=/{print $2; exit}' "$DIR/gpu.env.snippet" || true)"
  if [[ -n "$existing" ]]; then
    PASS_WORD="$existing"
  fi
fi
if [[ -z "${UVA_RTMP_USER:-}" && -f "$DIR/gpu.env.snippet" ]]; then
  existing_user="$(awk -F= '/^UVA_RTMP_USER=/{print $2; exit}' "$DIR/gpu.env.snippet" || true)"
  if [[ -n "$existing_user" ]]; then
    USER_NAME="$existing_user"
  fi
fi
if [[ -z "$PASS_WORD" ]]; then
  PASS_WORD="$(openssl rand -hex 10)"
fi

if [[ ! -x "$DIR/mediamtx" ]]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  if [[ -n "$LOCAL_TGZ" && -f "$LOCAL_TGZ" ]]; then
    echo "使用本地包 $LOCAL_TGZ"
    tar -xzf "$LOCAL_TGZ" -C "$tmp"
  else
    url="https://github.com/bluenviron/mediamtx/releases/download/${VER}/mediamtx_${VER}_linux_amd64.tar.gz"
    echo "下载 $url"
    if ! curl -fsSL --connect-timeout 10 --max-time 120 "$url" -o "$tmp/mtx.tgz"; then
      proxy="https://ghproxy.net/${url}"
      echo "直连失败，改走 $proxy"
      curl -fsSL --connect-timeout 10 --max-time 120 "$proxy" -o "$tmp/mtx.tgz"
    fi
    tar -xzf "$tmp/mtx.tgz" -C "$tmp"
  fi
  if [[ ! -f "$tmp/mediamtx" ]]; then
    echo "包里没有 mediamtx 可执行文件" >&2
    exit 1
  fi
  install -m 0755 "$tmp/mediamtx" "$DIR/mediamtx"
  trap - EXIT
  rm -rf "$tmp"
fi

umask 077
# '\r' 在 bash 单引号里是两个字符，去 CRLF 必须用 $'\r' 或 \015。
tr -d '\015' < "$SCRIPT_DIR/mediamtx.yml.template" | sed \
  -e "s/__RTMP_USER__/${USER_NAME}/g" \
  -e "s/__RTMP_PASSWORD__/${PASS_WORD}/g" \
  > "$DIR/mediamtx.yml"
chmod 600 "$DIR/mediamtx.yml"

cat > "$DIR/gpu.env.snippet" <<EOF
# 粘进 GPU 机器项目根 .env（不要提交）
UVA_RTMP_PULL_URL=rtmp://${PUBLIC_HOST}:1935/live/uva
UVA_RTMP_PUBLISH_URL=rtmp://${PUBLIC_HOST}:1935/live/uva
UVA_RTMP_USER=${USER_NAME}
UVA_RTMP_PASSWORD=${PASS_WORD}
EOF
chmod 600 "$DIR/gpu.env.snippet"

tr -d '\015' < "$SCRIPT_DIR/uva-edge.service" > /etc/systemd/system/uva-edge.service
chmod 0644 /etc/systemd/system/uva-edge.service
systemctl daemon-reload
systemctl enable --now uva-edge.service
sleep 2
if ! systemctl is-active --quiet uva-edge.service; then
  journalctl -u uva-edge.service -n 30 --no-pager >&2
  exit 1
fi
systemctl is-active uva-edge.service

if command -v ufw >/dev/null 2>&1; then
  ufw allow 1935/tcp comment 'uva rtmp ingest' || true
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port=1935/tcp || true
  firewall-cmd --reload || true
fi

echo
echo "收流节点已启动。云厂商安全组还要放行 TCP 1935。"
echo "凭证在 ${DIR}/gpu.env.snippet，拷到 GPU 机器项目根 .env，不要提交、不要打印。"
echo "GPU："
echo "  .\\run_uva.ps1 ingest-rtmp --edge --duration 30"
echo "  .\\run_uva.ps1 worker --until-empty"
echo
echo "本机健康检查: curl -s http://127.0.0.1:9997/v3/config/global/get"
