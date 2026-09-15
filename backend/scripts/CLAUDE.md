# CLAUDE.md — backend/scripts/

一次性运维脚本（手动 `uv run python scripts/<脚本>.py` 执行，直连根 `.env` 指向的 MySQL）。

## 脚本

- `cleanup_seed_demo.py`：删除线上库中由 `app/core/seed.py` 灌入的演示数据（演示焊缝 0245~0248 及版本/核验/标注、假数据集 熔池分割数据集/工艺质量预测集 及假版本、3 个演示模型及版本、关联 Jobs）。`--dry-run` 只预览不提交。**坑：**
  - `datasets.current_version_id ↔ dataset_versions`、`data_records.latest_version_id ↔ data_versions` 是两对环引用，删除前须先 `UPDATE ... SET ... = NULL` 置空；
  - `data_records.dataset_id` 引用 `datasets`，须先删焊缝再删数据集；
  - 真实焊缝若误挂在演示数据集下（曾出现 REG-20260815-00004 挂在 工艺质量预测集），脚本会挪回真实数据集（id=1）再删；
  - 脚本失败自动回滚（整个 Session 一个事务，仅末尾 commit）。
- `backfill_ingest_events.py`：按新的 `detect_events` **重算已入库的 `signal_ingests.events/anomalies`**
  （`--dry-run` 预览 / `--weld WLD-...` 限定单条焊缝）。用途：`events` 只在导入时算一次并存在行里
  （`load_signal_bundle` 直接读该行，不重算），而 `POST …/raw-files` 对已存在的 `(version_id,
  source_object_key)` 一律 409 不重跑——算法修复后线上存量数据不会自愈。CSV 按 `source_object_key`
  从 MinIO 重读，`column_map`/`sample_rate` 沿用行内存值（与当初导入同一套输入，无需重新校验）。
  **连带重算 `DataRecord.data_fields` 与 `wire_feed_speed`/`welding_speed`**——它们都取
  `events.weld_segment` 作稳态窗口（`_steady_window`），events 变了必须跟着变，否则登记详情里的
  工艺列还是旧窗口的中位数。首次执行（2026-09-15）修正 4 条：`WLD-20260903-0002` 焊接段
  0.133s→18.196s、`WLD-20260815-0003` 83.204s→83.244s。

## 子目录

- `premise_validation/`：集成 MLflow/Label Studio 的验证与实况 e2e 脚本（`run_premise_validation.py` 本机可自动化 4 项 + `probe_live.py` 真实 LS 2 项 + `probe_ls_sdk.py` SDK 方法名核对 + `probe_ls_region.py` region JSON 回读 + `e2e_ls_roundtrip.py` **真实全链路 e2e**：真样本→推 LS→SDK 标注→模拟 webhook 回写→幂等），命名不匹配 pytest 收集规则、不污染门禁，详见其目录 CLAUDE.md；结论文档 `docs/superpowers/specs/2026-09-05-integration-premise-verification.md`。

## 调用链

无被调用方（手动运维入口）；调用 `app.core.db.engine`。
