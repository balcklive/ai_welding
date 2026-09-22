# CLAUDE.md — backend/alembic/versions/

Alembic 迁移脚本目录（逐版本推进，全部由 `alembic revision` 生成，序号递增）。父目录 `backend/alembic/CLAUDE.md` 描述迁移约定与运行方式。

## 文件（按迁移顺序）

- `0001_initial.py`：初始建表（全部业务表，datetime 统一 `DATETIME(6)`；环形 FK 用「先建父表 → 子表 → `op.create_foreign_key` 补指针」处理 `data_records.latest_version_id ↔ data_versions.record_id`）。
- `0002_signal_ingests.py`：新增 `signal_ingests` 表（真实信号导入元数据，Task 18）。
- `0003_idempotency_request_keys.py`：登记/版本等 `request_key` 幂等约束。
- `0004_retry_failed_request_keys.py`：failed 释放 `request_key` 后可重试。
- `0005_audit_resource_id_255.py`：`audit_logs.resource_id` 扩到 255（兼容长 object key）。
- `0006_registration_dataset.py`：`data_records.dataset_id` 新增（登记必须归属数据集）。
- `0007_annotation_kind.py`：`annotations` 新增 `kind`/`points`/`start_time`/`end_time`（标注三模式）。
- `0008_registration_dataset_not_null.py`：`dataset_id` 收紧为 NOT NULL。
- `0009_feature_extraction_metadata.py`：`feature_extractions` 元数据补充。
- `0010_job_request_key.py`：Job 层 `request_key` 幂等（active_request_key 释放语义）。
- `0011_mlflow_run_id.py`：`jobs.mlflow_run_id`（模型中心 Job ↔ MLflow Run 关联，Task 16 真实训练）。
- `0012_registration_fields.py`：`data_records` 新增 `wire_feed_speed`/`welding_speed`（单值工艺参数，可表单录入/导入稳态回填）与 `data_fields`（JSON 字段概览，CSV 导入自动写），三列均 nullable（多模态分析.csv 全字段导入配套）。
- `0013_label_studio_integration.py`：**LS 集成（2026-09-05）**——`annotation_tasks` 新增 `ls_status`（VARCHAR(16) NOT NULL default `legacy`，存量回填 legacy）＋ 新表 `annotation_ls_sync`（§3.25，`(annotation_task_id, sample_id)` 复合唯一）。**坑**：用 `ADD COLUMN ... NOT NULL DEFAULT 'legacy'` 单条完成存量回填 + 新行默认 + 蓝绿 expand 兼容，勿拆成"可空列+UPDATE+contract"。
- `0014_label_category_pool.py`：**LS 集成决策 4（2026-09-06）**——`label_categories` 补第 6 类「熔池」（颜色 `#f032e6` 对齐 LS 项目4），纯数据迁移（无表结构变更），`INSERT ... ON DUPLICATE KEY UPDATE` 幂等。
- `0015_option_items.py`：**2026-09 系统设置·可选项字典**——新建 `option_items` 表 + `label_categories` 补 `sort_order`/`active`。
- `0016_dataset_item_annotations.py`：**T16.1 冻结标注快照**——`dataset_items` 加 `annotations` JSON。
- `0017_split_current_voltage.py`：**T4b/D7**——`data_records` 增 `current_a`/`voltage_v` 并从旧列解析回填。
- `0018_calibration_mapping.py`：**多模态统一坐标系（2026-09-22）**——`data_versions` 增 `calibration` JSON（人工标定：视频 `offset_seconds` + 焊缝图片 `roi`）、`alignment_tasks` 增 `mapping` JSON（算出的可执行映射：`linear` 视频 offset / `arc_length` 焊缝图片弧长）。纯 expand，两列均 nullable，老代码不读新列，新代码对 NULL 兜底（未标定 → `aligned=false` + reason，不阻断分段）。见 `docs/多模态时间统一样本分段重构设计方案.md` §3.1。

## 调用链

- 被谁调用：`alembic upgrade head`（容器 CMD 启动时执行 + 本地迁移）、`backend/app/core/health.py::expected_database_revision`（readiness 读唯一 head 比对）。
- 调用谁：仅 alembic API + `app.models` 元数据（env.py 收集）。

## 关键规则/坑

- **新增表/改字段必须同步**：新增迁移 + `docs/数据库设计.md` + `app/models/*/CLAUDE.md` + `backend/app/models/__init__.py` 的 `__all__`。
- 迁移文件含 UTF-8 中文 docstring；Python 源码按 UTF-8 解码，与服务器 locale 无关。
- 生产 readiness 会比对 `alembic_version.version_num` 与镜像内 alembic head：迁移未执行到 head 时 `/health/ready` 返回 503（部署候选容器预检由此保证迁移先于切流量）。
- **每次容器启动都跑 `alembic upgrade head`**（幂等），DB 不可达时容器退出，由部署回退机制处理。
