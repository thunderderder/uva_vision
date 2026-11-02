# UVA 收流节点（edge）

角色拆开，换机器只改环境变量。

| 角色 | 跑什么 | 现在（测试） | 以后（公司） |
|------|--------|--------------|--------------|
| edge | 仅 MediaMTX，公网收 RTMP | 个人 ECS | 公司云主机 |
| gpu | 出站拉流 → 抽帧入队 → YOLO/Qwen → IMS | 本机显卡 | 公司 4090 |
| 发布端 | 大疆 / ffmpeg `-re` | 本机模拟推流 | 机场/无人机 |

edge 不装 PyTorch、不跑 worker。gpu 不对外开 1935。

## 安装 edge（任意 Linux）

在目标机上：

```bash
sudo PUBLIC_HOST=<公网IP或域名> ./install_edge.sh
```

国内云主机经常拉不下 GitHub。把 `mediamtx_v1.20.1_linux_amd64.tar.gz` 放在本脚本同目录再装（本机可从 GitHub Release 下好再 scp）。脚本优先用这个包，没有才尝试直连 / ghproxy。

脚本会生成推流账号，写入 `/opt/uva-edge/gpu.env.snippet`。把这四行拷到 **GPU 机器** 项目根 `.env`，不要提交、不要把密码贴进聊天。主机防火墙脚本会尝试放行 1935；云厂商安全组也要放行 **TCP 1935**。若安全组已开、本机能 SYN 通，但 FFmpeg 报 `Cannot read RTMP handshake response`、ECS 上 `tcpdump -i any port 1935` 又看不到包，多半是云防火墙在边缘 SYN-ACK 之后把载荷丢掉。这时不要改代码：在控制台关掉该端口的扫描防护，或 GPU 先走 SSH 隧道验收整条链路。

MediaMTX 的 RTMP 账号走 query：`rtmp://主机:1935/live/uva?user=...&pass=...`。`run_uva.ps1` 会从 `.env` 自动拼，不要写成 `user:pass@主机`。

迁公司云：同一目录拷过去再跑一遍 `install_edge.sh`（已有凭证会沿用）。GPU 在公司内网就改 `.env` 里的主机名为内网 IP，不必出公网、也不必隧道。机场/无人机要推公网时，再在那台 edge 的安全组放行 1935。GPU 机器只改 `.env`，不改代码。

## GPU 机器怎么跑

本机模拟（不经过 edge）：

```powershell
.\run_uva.ps1 ingest-rtmp --duration 20
.\run_uva.ps1 worker --until-empty
```

经 edge 转发（模拟无人机推到收流节点，再拉回来处理）：

```powershell
.\run_uva.ps1 edge --video data\runtime\derived\fishing_1080p.mp4 --duration 20
```

等价于 `ingest-rtmp --edge` 再 `worker --until-empty`。`.env` 里的公网 URL 即可，2026-09-07 已从本机打通个人 ECS 的 1935。

公网 1935 又被云防火墙拦时，GPU 本机先开隧道再覆盖 URL：

```powershell
ssh -N -L 1935:127.0.0.1:1935 -i $env:USERPROFILE\.ssh\your-edge-key.pem root@<edge主机>
.\run_uva.ps1 edge --pull-url rtmp://127.0.0.1:1935/live/uva --publish-url rtmp://127.0.0.1:1935/live/uva --video data\runtime\derived\fishing_1080p.mp4 --duration 20
```

真机 / 司空已经在推，GPU 只拉。worker 不要加 `--until-empty`，队列空了还要继续等下一帧。另开窗口反复跑 `.\run_uva.ps1 hops`：`mediamtx` 那一行出现「发布 1 路」才说明司空推上了 ECS。司空地址必须是 `rtmp://主机:1935/live/uva?user=uva&pass=…`（query 鉴权，密码在 GPU 机器 `.env` 的 `UVA_RTMP_PASSWORD`）。安全组 1935 测试期不要只放你家 IP，司空来自大疆云机房。排查见 [`docs/hops.md`](../../docs/hops.md)。

```powershell
.\run_uva.ps1 ingest-rtmp --edge --no-publish --duration 60
.\run_uva.ps1 worker
.\run_uva.ps1 hops
```

只推不拉（直播一直挂着）：

```powershell
.\run_uva.ps1 publish --video data\runtime\derived\fishing_1080p.mp4
```

IMS 仍由 GPU worker 出站调用 MCP，edge 不碰巡查结果表。
