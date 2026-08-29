# CLAUDE.md — tools/

一次性/本地辅助脚本（不入运行时，不参与打包）。用 uv 管理 Python 环境（`uv run <script>`）。

## 文件

- `generate_training_signal.py`：生成确定性训练信号 fixture——写 `data/synthetic_training_signal.csv`（500 行，0.5s，列 `time/Current/Voltage/GasSpeed/WireSpeed`，起弧 0.10~0.44s 内电流/电压有值、其余 0），供 Playwright 训练流程用真实 CSV 导入。纯标准库（csv/math/pathlib），无第三方依赖。

## 调用链

- 被谁调用：手动/验收脚本调用；输出 `data/`（gitignore 或本地临时，不入仓库）。
- 调用谁：无。

## 关键规则/坑

- 输出路径锚定仓库根 `data/`（`parents[1]`），与 cwd 无关。
- 脚本目的明确、无副作用的工具放本目录；需长期维护的生成器再考虑迁入 `backend/tests/fixtures/` 或 `app/services`。
