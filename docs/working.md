# working.md

## Changelog

### 2026-11-02

- 文档与 README 收束为纯技术架构表述；移除演练方案类文档。
- README 补充内核/工作台分层思想与标准使用路径。
- 验证：`pytest tests/ -q` 全绿。

## Lessons Learned

- `config/pra_runtime.yaml` 仅本地、必须 gitignore。
- HTTP 预警与 RTMP 收流应分开联调（先 record_only）。
