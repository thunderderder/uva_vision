# uva_vision

无人机航拍场景的**本地视觉告警栈**：检测与复核在 GPU worker 里跑完，结果进 SQLite 队列，再按需推到业务系统（IMS MCP、第三方 HTTP 预警等）。本仓库同时提供 **UVA 内核**（收流、推理、出站）和 **工作台**（Web 配置、链路状态、Worker 生命周期），面向集成开发与现场联调。

## Privacy

**This repository is designed to be publishable with only fake examples.** 复制 `.env.example` → `.env` 后填入部署侧密钥与表单 ID；模型权重、`data/runtime/`、大体积媒体文件不要提交 git。

## 核心思想

### 架构：内核 + 工作台

系统**刻意**拆成两层，职责固定：

| 层          | 代码                       | 做什么                                                | 不做什么          |
| ---------- | ------------------------ | -------------------------------------------------- | ------------- |
| **UVA 内核** | `src/uva`、`src/pipeline` | RTMP/文件入队、YOLO→Qwen 推理、去重、证据图、IMS/审计               | 不提供面向业务的复杂 UI |
| **工作台**    | `src/uva_pra`            | Web：改 YAML 级参数、看队列与 hops、启停 Worker、飞流 dry-run/live | 不重写检测/复核算法    |

内核是**唯一推理真源**；工作台只 orchestrate——读 `config/pra_*.yaml` 和 `.env`，把字段映射成 worker 的 `runtime_config`，用子进程跑 `uva worker`。这样调参、开关推送、换模型路径时**不必改 Python 源码**，也不会 fork 一套流水线。

### 数据流（一条 job 的一生）

```
RTMP / 视频文件 / 图片文件夹
        → ingest（抽帧、telemetry）
        → SQLite job 队列
        → worker：YOLO（World 或闭集）→ Qwen-VL 复核 → 空间去重
        → 证据图 + audit 事件
        → 可选：IMS MCP、HTTP 预警（默认 record_only 落盘）
```

RTMP **收流**与 HTTP **外发**相互独立：可以先 `record_only` 核对 JSON，再切 `live` 真 POST。RTMP 拓扑见 `docs/rtmp_topology.md`。

**HTTP 预警（飞流）**：出站 JSON 按飞流机库接口要求的字段实现——`algoId`、`NestId`、`picData`（JPEG 字节的 Base64，无 `data:image/...` 前缀）。实现见 `src/uva_pra/feiliu.py`（`build_payload`）；URL、`NestId`、检测类型→`algoId` 映射在工作台 / `config/pra_*.yaml` 的 `push.*` 段配置。联调时默认 `feiliu_mode: record_only`，请求体会写入 `data/runtime/push_records/feiliu_*.json`。

### 配置从哪来

1. `.env` — 密钥、RTMP 端点、模型目录、IMS 表单 ID
2. `config/pra_defaults.yaml` — 进库的默认（端口、GPU/VLM 开关、推送模式）
3. `config/pra_runtime.yaml` — Web 保存的覆盖项（本地生成，已 gitignore）

Worker 启动前由工作台合并 defaults + runtime，并应用 `device.gpu_enabled`（无 GPU 时可关 VLM）。

## 使用方法

### 安装

Python 3.10+。CUDA 推理需在本 venv 内安装 GPU 版 PyTorch（`pip install -e ".[gpu]"` 体积较大）。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install -e ".[gpu]"    # 需要 GPU 时
copy .env.example .env
```

模型权重（不进 git，需自行下载到约定路径）：

| 用途 | 默认路径 | 拉取方式 |
|------|----------|----------|
| **YOLO-World（开放词，默认检测）** | `model/yolo/yolov8s-world.pt` | 创建目录后下载 Ultralytics 发行权重（文件名可与仓库默认不一致，下载 `worldv2` 后重命名即可）：<br>`mkdir model\yolo`（Linux/macOS：`mkdir -p model/yolo`）<br>`curl -L -o model/yolo/yolov8s-world.pt https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-worldv2.pt`<br>说明：[YOLO-World 文档](https://docs.ultralytics.com/models/yolo-world/) · [assets 发行页](https://github.com/ultralytics/assets/releases)。 |
| **YOLOv8s（COCO 闭集）** | `model/yolo/yolov8s.pt`（或 `.env` 的 `UVA_YOLO_V8S_WEIGHTS`） | `curl -L -o model/yolo/yolov8s.pt https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s.pt`（仅在工作台选用闭集 `yolov8s` 预设时需要）。 |
| **Qwen3-VL-2B（复核）** | `model/vl/qwen-vl/2B-Instruct`（或 `.env` 的 `UVA_QWEN_DIR_PATH`） | **推荐（需网络 / Hugging Face）：**<br>`python -m uva download-qwen-vl`<br>指定目录：`python -m uva download-qwen-vl --dir model/vl/qwen-vl/2B-Instruct`<br>对应仓库：[Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)（`model_assets.py` 默认 `repo_id`）。<br>**镜像：** 可从 [ModelScope 同名模型](https://modelscope.cn/models/Qwen/Qwen3-VL-2B-Instruct) 下载整目录到上述路径，并保证含有效 `config.json`（含 `model_type`）。 |

拉取前请先 `mkdir -p model/yolo model/vl/qwen-vl`（Windows：`mkdir model\yolo, model\vl\qwen-vl`）。千问下载依赖 `pip install -e ".[gpu]"` 里的 `huggingface-hub`；HF 超时可配置镜像或改用 ModelScope 手工拷贝。

Shell 入口：`scripts/run_pra.sh` / `scripts/run_uva.sh`（Linux/macOS）。Windows 也可用下方「命令行」方式，不必依赖 `.ps1`。

### 日常操作

**1. 启动工作台**

Windows 便捷脚本（自动设 `PYTHONPATH`、优先用 `.venv`）：

```powershell
.\run_pra.ps1 serve
```

跨平台命令行（在仓库根目录、已激活 venv 且已 `pip install -e ".[dev]"` 或 `".[gpu]"`）：

```powershell
python -m uva_pra serve
# 可选：python -m uva_pra serve --host 127.0.0.1 --port 8030
```

Linux/macOS 等价：`./scripts/run_pra.sh serve`，或同样使用 `python -m uva_pra serve`。

浏览器打开 http://127.0.0.1:8030（默认端口见 `config/pra_defaults.yaml`）。

**2. 启动 Worker**

在 Web **配置**页启动 / 重启 Worker，或：

```powershell
.\run_pra.ps1 worker --until-empty
```

**3. 喂数据（CLI）**

```powershell
.\run_uva.ps1 ingest-rtmp --duration 20
.\run_uva.ps1 ingest-file path\to\video.mp4
.\run_uva.ps1 hops
```

**4. 可选：仅内核审计页**

```powershell
.\run_uva.ps1 audit
```

### 仓库布局

| 路径 | 说明 |
|------|------|
| `src/uva_pra/` | FastAPI 工作台、飞流客户端、Worker 管理 |
| `src/uva/` | CLI、store、ingest、worker、IMS |
| `src/pipeline/` | YOLO / VLM 流水线模块 |
| `config/` | 默认配置 + 本地 runtime 覆盖 |
| `docs/` | RFC、测试策略、RTMP/HTTP 集成说明 |
| `deploy/edge/` | MediaMTX 边缘收流（可选） |

### 开发与验证

```powershell
python -m pytest tests/ -q
python -m pytest tests/test_publishable.py -q
```

接手维护前读 `AGENTS.md`；架构细节见 `docs/rfc.md`。
