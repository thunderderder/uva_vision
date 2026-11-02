# RTMP 收流拓扑（直连 vs ECS 中转）

## 结论

**有 RTMP 且算法机（GPU 服务器）能被发布端访问时，不必再经云服务器 MediaMTX 转一道。**

ECS 中转解决的是历史约束：GPU 在本机宽带/NAT 后，大疆司空只能推到公网入口；入口用一台有公网 IP 的 ECS 收流，GPU 再从 ECS 拉。

迁到**常驻服务器**（公网 IP 或端口映射、或 VPN 内网）后，推荐：

| 模式 | 配置 `rtmp_mode` | 行为 |
|------|------------------|------|
| **直连（推荐）** | `direct_local` | 服务器本机起 MediaMTX；司空/无人机推到 `rtmp://你的服务器:1935/live/uva?user=&pass=`；工作台或 `ingest` 只从本机 `127.0.0.1` 拉流抽帧 |
| **ECS 中转（兼容旧链路）** | `edge_relay` | 不启本机 MTX；`UVA_RTMP_PULL_URL` 指向 ECS；GPU 从 ECS 拉 |
| **第三方拉流（萤石等）** | `remote_pull` | 不启本机 MTX；工作台填完整 `rtmp://…`（自带鉴权 query），**不会**拼 `UVA_RTMP_USER` |
| **本机演练模拟** | `simulate` | 本机 MTX + ffmpeg 用 mp4 模拟推流 |

## 工作台操作

「链路」页：选择收流模式 → **开始收流** / **停止**。需另开终端 `.\run_pra.ps1 worker`（常驻，不要 `--until-empty`）。

## 环境变量（仍在 `uva/.env`）

- `UVA_RTMP_URL`：本机 MediaMTX 地址（直连时一般为 `rtmp://127.0.0.1:1935/live/uva`）
- `UVA_RTMP_PULL_URL`：仅 `edge_relay` 需要，填 ECS 拉流地址
- `UVA_RTMP_USER` / `UVA_RTMP_PASSWORD`：query 鉴权，勿写成 `user:pass@host`

## hops 怎么读

`tcp_1935` / `mediamtx` 在 **直连** 时应对准**算法服务器**或本机，不必 ECS 全绿。`gpu_queue` 涨、worker 在跑，即链路有效。
