# RFC — uva_vision 架构

## 1. 包与目录

```
project_root/
├── src/uva_pra/     # 工作台（FastAPI、pra 配置、HTTP 预警、Worker 子进程）
├── src/uva/         # 产品壳 CLI、ingest、worker、store、IMS
├── src/pipeline/    # 检测 / VLM 模块（import 名 modules.*）
├── config/          # pra_defaults + 本地 pra_runtime（gitignore）
└── data/            # runtime（gitignore）、eval 冻词样例
```

`uva_pra.bootstrap`：`PROJECT_ROOT` 即仓库根，`.env` 在根目录；`ensure_uva_paths()` 挂载 `src` 与 `src/pipeline`。

## 2. 运行时进程

| 进程 | 入口 | 职责 |
|------|------|------|
| 工作台 Web | `python -m uva_pra serve` | HTTP API + 静态 UI |
| Worker | `python -m uva_pra worker` 或 `python -m uva worker` | 拉 SQLite job，跑 `kernel.infer_frame` |
| Ingest | `python -m uva ingest-*` | 写 job，不加载大模型 |
| 审计页（可选） | `python -m uva audit` | 仅画廊，可与工作台并存 |

工作台内 `WorkerManager` 以子进程启动 worker，日志 `data/runtime/logs/pra_worker.log`。

## 3. 推理链（kernel + pipeline）

1. `frame_detect` / 切片 + `global_box_nms`（大图）  
2. `VisualPrompter` + `vlm_verifier`（layout: full_frame / roi / per_box）  
3. `Postprocessor` → alerts；`dedup` 网格冷却  
4. `evidence.write_job_evidence`；`store` 写 result / events  

配置默认值在 `pipeline/config.py`；运行时 overrides 来自 pra 映射（`uva_pra.runtime_ui`）。

## 4. 出站

- **IMS**：`worker` 内 `ImsMcpWriter` / 传统 form API；字段 ID 在 `ims_push.FIELDS`，部署时必须换成目标表单。  
- **HTTP 预警**：`uva_pra.feiliu`，模式 `record_only` | `live`；POST 体字段对齐飞流要求（`algoId` / `NestId` / `picData`），映射与 URL 在 `push` 配置。

幂等与重试：push 记录 + audit 投影（`audit_view`）。

## 5. pipeline 兜底

`modules/__init__.py` 可在缺失 `.py` 时从 `__pycache__` 加载；仓库内主要模块已为源码。升级 Python 小版本前应确认无 pyc 依赖。

## 6. 配置优先级

`.env` > 环境变量 > `pra_runtime.yaml` > `pra_defaults.yaml` > `pipeline/config.py` 默认。

## 7. 边缘 RTMP

`deploy/edge/` 提供 MediaMTX 安装模板；GPU 机可 `ingest-rtmp --edge` 只拉流不启本机 MTX。拓扑说明见 `docs/rtmp_topology.md`。
