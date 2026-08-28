# CLAUDE.md — backend/scripts/

一次性运维脚本（手动 `uv run python scripts/<脚本>.py` 执行，直连根 `.env` 指向的 MySQL）。

## 脚本

- `cleanup_seed_demo.py`：删除线上库中由 `app/core/seed.py` 灌入的演示数据（演示焊缝 0245~0248 及版本/核验/标注、假数据集 熔池分割数据集/工艺质量预测集 及假版本、3 个演示模型及版本、关联 Jobs）。`--dry-run` 只预览不提交。**坑：**
  - `datasets.current_version_id ↔ dataset_versions`、`data_records.latest_version_id ↔ data_versions` 是两对环引用，删除前须先 `UPDATE ... SET ... = NULL` 置空；
  - `data_records.dataset_id` 引用 `datasets`，须先删焊缝再删数据集；
  - 真实焊缝若误挂在演示数据集下（曾出现 REG-20260815-00004 挂在 工艺质量预测集），脚本会挪回真实数据集（id=1）再删；
  - 脚本失败自动回滚（整个 Session 一个事务，仅末尾 commit）。

## 调用链

无被调用方（手动运维入口）；调用 `app.core.db.engine`。
