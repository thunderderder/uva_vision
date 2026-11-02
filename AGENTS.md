# AGENTS.md — uva_vision

本地视觉告警栈 + Web 工作台。先读 `README.md` 与 `docs/rfc.md`；改代码后更新 `docs/working.md`。

## 结构

- `src/uva_pra/` — 工作台（Web、pra YAML、HTTP 预警、Worker 子进程）
- `src/uva/` — ingest、worker、store、IMS、审计 CLI
- `src/pipeline/` — YOLO / VLM 模块
- `config/pra_defaults.yaml` — 默认；`pra_runtime.yaml` 本地覆盖，**gitignore**
- `data/runtime/` — SQLite、证据、推送记录，**勿提交**

## 环境

- Python ≥ 3.10；`pip install -e ".[dev]"` 跑测试；GPU 用 `".[gpu]"`。
- `.env.example` → `.env`；禁止把真实密钥写进 tracked 文件。
- 入口：`run_pra.ps1` / `run_uva.ps1` 或 `python -m uva_pra` / `python -m uva`。

## 硬规则

1. 有意义改动写 `docs/working.md` 当日 Changelog。  
2. 小步 commit。  
3. 公开文件禁止本机绝对路径、真实凭据、内部 monorepo 路径（`tests/test_publishable.py`）。  
4. 逻辑进 `src/`，保留 `run_*.ps1` 入口。  
5. 不重写 kernel 推理；工作台只做配置与进程编排。  

## 验证

```powershell
python -m pytest tests/ -q
python -m pytest tests/test_publishable.py -q
```

## 文档

- 范围：`docs/prd.md`  
- 架构：`docs/rfc.md`  
- 测试：`docs/test.md`  
