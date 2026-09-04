# CLAUDE.md — backend/app/models/

SQLModel 表类（全部 24 张，`table=True`）。当前进度：Task 2（全部模型 + `__init__.py` 导出）+ **Task 18（新增 `SignalIngest`，§3.24）**。

## 文件与内容

- `__init__.py`：re-export 全部 23 个表类。**Alembic env.py `from app.models import *` 依赖它**收集全部表到 `SQLModel.metadata`；新增表必须同步加进 `__all__`。
- `data.py`：`User`(§3.1)、`DataRecord`(§3.2)、`DataVersion`(§3.3，`request_key`：加工版本并发幂等)、`ValidationReport`(§3.4)、`ValidationRuleResult`(§3.5)、`AuditLog`(§3.23，**Task 5 P2**：`resource_id` 现按迁移 `0005` 扩到 255，兼容长 object key）。`DataRecord.dataset_id` 由迁移 `0006` 增加，登记必须归属数据集；历史兼容字段暂允许空值，业务/API 不允许新登记为空。**2026-09 多模态字段**：`wire_feed_speed`/`welding_speed`（单值工艺参数，登记可填/CSV 导入稳态回填）+ `data_fields`（JSON 字段概览 `[{id,name,unit,value}]`，导入自动写，前端展示），见迁移 `0012`。
- `jobs.py`：`Job`(§3.6) 统一异步任务生命周期。
- `analysis.py`：`AlignmentTask`(§3.7，`request_key` 保留逻辑幂等历史，`active_request_key` 仅给 pending/running/succeeded 做唯一占位，failed 可释放后重试)、`SplitTask`(§3.8，同上)、`Sample`(§3.9)、`AnnotationTask`(§3.10)、`Annotation`(§3.11，**标注 kind 升级**：`kind`(box/segment/polygon) + `points`/`start_time`/`end_time` 四列，见迁移 `0007`)、`LabelCategory`(§3.12)、`FeatureExtraction`(§3.13)、`SignalIngest`(§3.24，**Task 18**：CSV 真实信号导入元数据，`(version_id, source_object_key)` 复合唯一幂等)。
- `datasets.py`：`Dataset`(§3.14)、`DatasetVersion`(§3.15)、`DatasetItem`(§3.16)、`DatasetBuildTask`(§3.22)。
- `models.py`：`Model`(§3.17)、`ModelVersion`(§3.18)、`TrainingTask`(§3.19)、`TestTask`(§3.20)、`InferenceTask`(§3.21)。

## 类型映射规则（与 `docs/数据库设计.md` §3 逐列一致）

| 文档列型 | 模型写法 |
|---|---|
| BIGINT PK | `id: int \| None = Field(default=None, primary_key=True)` |
| VARCHAR(n) | `x: str = Field(max_length=n, ...)` |
| DATETIME(6) | `x: datetime \| None = Field(default=None, sa_column=Column(DateTime(timezone=True)))`（迁移里 render 成 `mysql.DATETIME(fsp=6)`） |
| JSON | `x: list/dict \| None = Field(default=None, sa_column=Column(JSON))`；NOT NULL 带默认的用 `Field(default_factory=list, sa_column=Column(JSON))` |
| DECIMAL(p,s) | `sa_column=Column(Numeric(p, s))` |
| FK | `Field(foreign_key="表名.id", ...)` |
| 索引列 | `Field(index=True)`；单列唯一用 `unique=True` |
| 复合唯一 | `__table_args__ = (UniqueConstraint("a","b", name=...),)` |

## 坑/限制

- **环形 FK（勿删/勿"修复"）**：`data_records.latest_version_id → data_versions.id` 与 `data_versions.record_id → data_records.id` 互指（反规范化最新版本指针）；`datasets.current_version_id ↔ dataset_versions.dataset_id` 同理。SQLAlchemy 元数据按字符串 FK 名解析，正常；迁移里用"先建父表 → 再建子表 → `op.create_foreign_key` 补指针外键"处理。测试用 SQLite 内存，`drop_all` 会因环形依赖无法排序表（SAWarning），故测试改为每用例全新引擎。
- **created_at 等 NOT NULL 只在迁移保证**：模型允许 `None`，时间戳由服务层写入（保持 SQLite 测试简单）。
- **`quality`/`role`/`progress`/`passed`/`sample_count`/`status` 的文档 DEFAULT**：模型有 Python 侧默认，迁移里同时给了 `server_default`。
- 改模型字段时**必须同步**：`alembic/versions/0001_initial.py`（新增迁移）、`docs/数据库设计.md`、`app/models/CLAUDE.md`。
- `models` 表无 `created_at`（文档如此），`jobs.created_at/finished_at` 可空（文档如此）。
