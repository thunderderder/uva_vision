# 测试策略 — uva_vision

## Unit（默认 / 离线）

`pytest tests/ -q` 不依赖 GPU、权重或网络。

- `uva_pra`：配置合并、HTTP 预警 payload、runtime UI、测试数据重置  
- `uva`：contract、store、dedup、RTMP URL、audit 投影、IMS payload（mock）  
- `pipeline`：detector 分支、VLM parse、NMS、postprocessor  

## Integration（本机 opt-in）

需要 CUDA、`".[gpu]"`、权重与可选 MediaMTX。

1. `run_pra.ps1 serve` + Web 启动 Worker  
2. `run_uva.ps1 ingest-file` 或 `ingest-rtmp`  
3. 检查 `data/runtime/uva.sqlite3`、证据目录、push JSON  

## E2E

无自动化浏览器测试；联调以 Web 链路页 + 画廊为准。

## 发布门禁

`tests/test_publishable.py` — 禁止私密路径与常见 secret 模式。

## 完成定义

- 默认 pytest 全绿  
- 新 venv 可按 README 启动 serve（Worker 可关 VLM）  
