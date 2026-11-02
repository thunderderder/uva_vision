# PRD — uva_vision

## 目标

为无人机航拍视频提供**可本地部署**的告警流水线：初筛检测 + 多模态复核 + 可审计队列 + 可插拔出站。

## 用户

- **集成 / 算法工程师**：调模型路径、阈值、prompt、推送开关，排查 ingest → worker → egress。  
- **现场技术**：确认有帧、有框、有出站记录（含 dry-run JSON）。

## 功能范围

| 能力 | 要求 |
|------|------|
| 输入 | RTMP 实时流、单文件/文件夹成片入队 |
| 推理 | YOLO-World 或闭集 YOLO；可选本地 Qwen-VL 复核 |
| 持久化 | SQLite 队列、证据图、推送与审计事件 |
| 出站 | IMS MCP（可关）；HTTP 预警 record_only / live |
| 工作台 | Web 配置、链路 hops、Worker 启停、结果画廊 |
| 非目标 | 云端 SaaS、训练平台、移动端 App |

## 成功标准（技术）

- 改 `config/pra_runtime.yaml`（经 Web 保存）后，新 job 行为可观测变化。  
- `record_only` 下每条预警可对照 `data/runtime/push_records/` 与 UI。  
- 默认 `pytest` 离线全绿；无 GPU 时可关闭 VLM 仍跑通 UI + 队列（仅 YOLO 或空队列）。

## 文档路由

| 主题 | 文件 |
|------|------|
| 架构 | `docs/rfc.md` |
| 测试 | `docs/test.md` |
| RTMP | `docs/rtmp_topology.md` |
