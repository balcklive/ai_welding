# 2026-08-29 数据集管理开源参考改造任务清单

> 背景：将数据集管理参考体系（数据标注=Label Studio、数据集管理=FiftyOne 界面 + Datumaro 处理能力 + lakeFS 版本思想、模型管理=MLflow）落到本项目。本文是**改造任务清单**，不是技术选型决定——三个开源项目**均不作为运行依赖/基础设施引入**，只借鉴思想、界面交互与处理能力，用现有 DB + MinIO + 前端落地。
>
> 结论一句话：FiftyOne 借"看"（样本浏览 + 质量评估）、Datumaro 借"造"（构建/划分/统计校验/格式）、lakeFS 借"管"（版本/血缘/可复现）；三者与本项目现有 `dataset_versions + dataset_items` 固定快照设计不冲突，反而是它的补强。

---

## 零、迁移路线总原则（借思想 · 不引依赖）

> **本迁移的唯一主线**：三个开源项目（FiftyOne / Datumaro / lakeFS）只借**思想、界面交互与处理能力**，一律用现有 DB（MySQL）+ MinIO + 前端落地；**不引入其中任何一个作为运行依赖或基础设施**。下文所有 DM 任务的取舍、以及今后涉及大数据量场景的实现，都以此为准。

**为什么"不引依赖"对本项目是最优解（四条硬约束）**：

| 约束 | 说明 |
|---|---|
| 数据源一致性 | FiftyOne 百万级浏览靠 MongoDB 聚合/索引；引入即需把 `dataset_items` 再同步一份 → 双份存储 + 同步延迟 + 快照一致性维护。`dataset_versions + dataset_items` 固定快照是业务真源，不做平行数据源 |
| 部署拓扑 | 本部署为单容器 Docker（FastAPI 同时服务 `/api` 与前端静态）+ 私有化；引入 = 多进程 + 多依赖（MongoDB / FiftyOne server），破坏单容器 |
| 规模在 MySQL 服务范围内 | 几十万~几百万行的浏览/预览，SQL 侧聚合 + 分页即可承担；FiftyOne 不可替代价值在 embeddings 可视化 / 语义检索 / 大规模模型评估，§三.4 已明确不做 |
| 改造代价 | 现有真实链路（成员浏览 / 标签分布 / 信号预览）只缺"系统性补齐"，比推倒重来 + 迁移数据便宜一个数量级 |

**复用边界（什么情况才值得引入）**：仅当**数据浏览本身成为产品主体**——百万样本上的语义检索 / embedding 相似度 / 复杂组合检索是核心功能时，自造成本才超过引入成本。本项目是焊接业务平台 + 数据治理 + 模型训练，浏览是业务动作的辅助、不是产品核心，故不适用。

**大数据量渲染/预览五条落地原则**（后续每个 DM 任务涉及大数据量场景时照此执行）：

| 场景 | 现有基础 | 优化动作（对应任务） | 借自 |
|---|---|---|---|
| 信号预览（910k 点/通道） | `signals.downsample_indices` min-max 抽稀 + `signal_ingest._cached_parquet` LRU 缓存 | 多级抽稀金字塔，缩放即时出图（DM-11） | FiftyOne 服务端投影 + lakeFS 直连 |
| 数据集成员列表（百万行） | SQL 侧过滤/计数/offset 分页（`list_version_items`） | keyset/游标分页 + 前端虚拟滚动（DM-10） | FiftyOne view 下推 |
| 统计类（标签分布/质量/类别平衡） | `label_distribution` 后端聚合小 payload | 服务端聚合 + 逐批迭代，不物化全量（DM-03） | FiftyOne aggregation / Datumaro 惰性求值 |
| 缩略图浏览 | 无（纯表格行） | 预生成小图存 MinIO + 可视区懒加载（DM-06） | FiftyOne thumbnail/grid |
| 大媒体预览 | 预签名直传（presign-upload） | 保持直连，预览同样走预签名 URL，不走 `/api` 代理 | lakeFS 直连对象存储 |

---

## 一、参考体系总览

| 项目 | 借的层 | 借什么 | 落在本项目哪个功能 | 明确不抄什么 |
|---|---|---|---|---|
| **FiftyOne** | 看（样本浏览/质量评估） | 字段筛选、标签分布、模态/质量问题筛选、GT+预测叠加预览 | 版本成员列表与筛选、数据集概览标签分布 | 不引入它的 Python SDK + 本地数据集服务器 + 内嵌 Web App 运行时 |
| **Datumaro** | 造（构建/统计/格式） | COCO/YOLO 导入导出、统计校验、标签分布保持划分、变换/合并 | 数据集构建流水线、quality 统计、切分策略、标注导出 | 不把"数据集=磁盘目录"模型引入；不做常驻依赖（仅薄转换器） |
| **lakeFS** | 管（版本/血缘/可复现） | 不可变提交、branch-per-experiment、按引用可复现、回滚 | `dataset_versions` 固定快照、lineage、训练引用、版本回滚 | 不引入 S3 网关 + Git 语义基础设施；不做完整分支/合并/回放 |

**已确认现状（写清单前核实过，勿重复做）**：
- `dataset_versions`（固定快照 + `version_no` v1.x + `split` + `item_count` + `quality` + `snapshot_id`）+ `dataset_items`（固定成员清单）已在 `backend/app/models/datasets.py`，**保留不动**。
- `snapshot_id` 目前是**确定性路径** `datasets/{version_id}/snapshot.json`（`backend/app/services/datasets.py:1131`），非内容哈希 → DM-08。
- lineage 4 层（原始焊缝→标注任务→数据集版本→模型训练）已有（`get_lineage`）→ **不再做**。
- 训练已引用 `dataset_version_id`（`training_tasks`），且 MLflow `record_training` 已记 `dataset_version_id` param（`backend/app/services/models.py:239-243`）→ DM-02 只需补快照摘要，**不必重新接 MLflow**。
- 数据集详情接口已返回 `label_distribution`（`backend/app/api/v1/datasets.py:120`）但前端没渲染 → DM-01 纯前端。
- 版本成员筛选目前仅 `q/quality/split`（`backend/app/api/v1/datasets.py:194-228`）→ DM-04。

---

## 二、改造任务清单

按优先级分组；每项含 参考来源 / 现状与 gap / 改造内容 / 涉及文件 / 验收标准。

### P0（低成本高收益，独立可做，建议最先）

#### [DM-01] 数据集概览渲染"标签分布"面板（FiftyOne 标签分布）

- **参考来源**：FiftyOne 标签分布侧栏。
- **现状 gap**：后端 `dataset_payload` 已带 `label_distribution`（`services/datasets.py:254`，详情路由 `api/v1/datasets.py:120` 传入），但前端 `DatasetDetail`（`src/features/datasets/DatasetWorkspace.tsx:178`）只消费 `quality/split`，标签分布没画出来。
- **改造内容**：`DatasetDetailContent` 概览区加"标签分布"面板，吃 `detail.label_distribution`（`{类别: 计数}`），画分布条/柱状；无当前版本或分布为空时显示空态。
- **涉及文件**：`src/features/datasets/DatasetWorkspace.tsx`（+ 可能 `index.css` 一个样式类）。后端/契约**零改动**。
- **验收**：打开数据集概览，显示当前版本各类别标注计数分布；空版本显示"暂无标注分布"。

#### [DM-02] 训练时把数据集快照摘要记入 MLflow Run（lakeFS 可复现 / 建议 4）

- **参考来源**：lakeFS"按引用可复现" + 原评估建议第 4 条（数据集版本与 MLflow Run 强关联）。
- **现状 gap**：`record_training` 已记 `dataset_version_id` param，但**没记**版本快照摘要（`version_no` / `item_count` / `split` / `quality`）与划分策略，MLflow Run 无法仅凭 Run 自证"用了哪个不可变快照、质量如何"。
- **改造内容**：
  1. `run_training` 训练成功后读取 `DatasetVersion` 的 `split` / `quality` / `item_count`；
  2. 以 params 记 `dataset_version_no`、`split_train/val/test`、`quality_repeat_rate` 等（数量可控，挑关键项）；
  3. 以 JSON artifact 记完整 `dataset_snapshot.json`（version_no / item_count / split / quality / snapshot_id）；
  4. 同时把快照摘要并入 `job.result`，前端训练结果可展示。
- **涉及文件**：`backend/app/services/models.py::run_training`、`backend/app/integrations/mlflow.py`（`record_training` 扩参，或新增 `record_dataset_snapshot`；保持 best-effort + 不抛异常铁律）。
- **验收**：`test_mlflow_integration.py` 覆盖——MLflow Run params 含 `dataset_version_no/split_*`，artifacts 含 `dataset_snapshot.json`；MLflow `off` 模式不炸。

#### [DM-03] 构建质量统计扩展 + 划分类别平衡（Datumaro 统计校验 + 标签分布保持划分）

- **参考来源**：Datumaro `stats`（类别分布/各 subset 统计）+ `validate`（缺标注/重复）+ 标签分布保持划分（stratified split）。
- **现状 gap**：
  - `_compute_quality`（`services/datasets.py:1053`）只有 `repeat_rate` / `empty_label_rate` / `dimension_missing_rate` 三个比率，**无类别级统计**；
  - `_assign_splits`（`services/datasets.py:1026`）按焊缝分组 seed=42 随机 8:1:1，**只防泄漏、不保类别平衡**——稀类别可能整组进单一 split。
- **改造内容**：
  1. `_compute_quality` 扩展：按 split 统计**各类别样本数** + **类别不平衡度**（max/min 或 Gini 简化指标），写 `version.quality` + `job.result`；保留原有三个比率（前端已消费，勿改名）。
  2. `_assign_splits` 升级为**约束下平衡划分**：先按焊缝分组（不可拆），组带标签组成向量；分配时在保持 8:1:1 总量的前提下，让各 split 的类别比例尽量接近全量（贪心/轮转分配即可，不必最优化）。**组数 <3 的退化逻辑保留**。
- **涉及文件**：`backend/app/services/datasets.py`（`_compute_quality` / `_assign_splits` / `_build_snapshot` 的 snapshot 结构）、`backend/app/jobs/dataset_build.py`（透传，基本不动）、`tests/test_datasets.py`。
- **验收**：新增单测——多类别样本构建后 `quality` 含类别分布；在分组允许的前提下，稀类别在 train/val/test 均出现（或至少不整组偏向单一 split）；原有"同焊缝不跨 split"断言仍绿。

### P1（需要跨层小改造，会员浏览增强）

#### [DM-04] 版本成员扩展筛选：模态 / 机器 / 来源 / 缺标注（FiftyOne 字段筛选 + 质量问题）

- **参考来源**：FiftyOne 按任意字段筛选 + 质量问题筛选（缺标注）。
- **现状 gap**：items 端点只支持 `q/quality/split`（`api/v1/datasets.py:194-228`）；`list_version_items`（`services/datasets.py:516`）SQL 已 outerjoin 到 `DataRecord`（source/machine/modalities），但筛选没用上；样本级"有无标注"也未入筛。
- **改造内容**：
  1. 后端 items 端点新增 query 参数：`modality`（多值，匹配 `record.modalities`）、`machine`、`source`（复用已 join 列做 SQL 筛选）；`labeled`（`true`/`false`）筛选该版本内**有/无标注**样本（`samples` 是否关联 `annotations`，exists 子查询，注意只按本版本成员集判定）。
  2. 前端 `DatasetRecords` 筛选条加"模态"多选 + "缺标注"开关；`listDatasetVersionItems` 参数扩展 + `api/types.ts` 类型。
- **涉及文件**：`backend/app/api/v1/datasets.py`、`backend/app/services/datasets.py::list_version_items`、`src/features/datasets/DatasetWorkspace.tsx`、`src/api/datasets.ts`、`src/api/types.ts`。
- **契约**：回写 `docs/API接口清单.md` §3.5 items 端点新参数。
- **验收**：成员页可按模态 / 缺标注服务端筛选，`tests/test_datasets.py` 覆盖新参数（含分页总数正确）。

#### [DM-05] 版本"设为当前快照"回滚（lakeFS checkout）

- **参考来源**：lakeFS checkout 历史提交。
- **现状 gap**：`datasets.current_version_id` 指针在，但**没有**把指针切回历史版本的接口/UI。
- **改造内容**：
  1. 新增 `POST /datasets/{dataset_id}/versions/{version_id}/activate`：校验版本属于该数据集（40402）→ 切 `current_version_id` + 更新 `updated_at` → `write_audit(activate)`；
  2. 前端版本列表每个历史版本加"设为当前快照"操作（`window.confirm` 确认）。
- **涉及文件**：`backend/app/api/v1/datasets.py`、`backend/app/services/datasets.py`、`src/features/datasets/DatasetWorkspace.tsx`（`DatasetDetailContent` 版本列表）。
- **契约**：回写 `docs/API接口清单.md` §3.5 新端点。
- **验收**：切回历史版本后 `GET /datasets/{id}` 的 `current_version_id/version/split/quality` 随之变化，`audit_logs` 有 activate 记录；版本不属于该数据集 → 40402。

#### [DM-06] 成员缩略图 + 标注叠加预览（FiftyOne GT+预测叠加）

- **参考来源**：FiftyOne 样本网格浏览器 + GT/预测叠加。
- **现状 gap**：成员列表是纯表格行（`DatasetRecords`），无缩略图/叠加预览。
- **改造内容**：成员列表加"网格视图"切换（与表格并列）；图像样本显示 `getFileUrl` 图片 + 该样本 `annotations` 的 box/polygon 叠加（轻量 canvas 叠加，或复用 `src/components/annotation/AnnotoriousImageEditor.tsx` 只读模式）。预测叠加（推理 boxes vs GT）列为可选后续，不在本期。
- **涉及文件**：`src/features/datasets/DatasetWorkspace.tsx`、可选 `src/components/annotation/AnnotoriousImageEditor.tsx`。
- **验收**：网格视图下图像样本显示标注框叠加；非图像样本显示占位图标。

#### [DM-10] 版本成员列表 keyset/游标分页（MySQL 大数据量深翻页）

- **参考来源**：FiftyOne view 下推 + MySQL 大数据量公认做法（offset 深翻页在百万行退化，三个参考项目均未显式覆盖此点）。
- **现状 gap**：`list_version_items`（`services/datasets.py:516`）用 offset/limit 分页，翻到深页后扫描开销线性增长；DM-04 扩筛后规模可能继续放大。
- **改造内容**：
  1. items 端点新增可选游标参数 `cursor`（上一页最后一个 `sample_id`），服务端走 `WHERE sample_id > cursor ORDER BY sample_id LIMIT n`；保留 `page/page_size` 兼容旧调用。
  2. 前端翻页在页码超过阈值（如 >100）后自动切换游标模式。
- **涉及文件**：`backend/app/api/v1/datasets.py`、`backend/app/services/datasets.py::list_version_items`、`src/features/datasets/DatasetWorkspace.tsx`、`src/api/datasets.ts`。
- **验收**：游标模式深翻页结果与 offset 模式在浅页一致、深页切片正确且 `total` 不变；旧 `page` 参数仍可用。

### P2（生态打通 / 快照硬化，可选）

#### [DM-07] 标注 / 数据集格式导出 COCO / YOLO（Datumaro 格式转换）

- **参考来源**：Datumaro 多格式导入导出。
- **现状 gap**：`export_annotations`（`services/annotation.py`）只导出自定义 segment JSON / mask PNG；无 COCO/YOLO。
- **改造内容**：新增薄转换器模块（**不引入 Datumaro 常驻依赖**）：标注导出可选 COCO（image/annotation JSON）或 YOLO（txt）；数据集版本快照 → COCO 导出，供外部训练/迁移。
- **涉及文件**：新增 `backend/app/services/dataset_formats.py`、`backend/app/services/annotation.py`（export 分支）、`backend/app/api/v1/analysis.py`（export body 扩展 format 参数）。
- **验收**：导出 COCO/YOLO 内容与 `annotations` 行一致；未知格式 → 400。

#### [DM-08] `snapshot_id` 改为内容哈希（lakeFS 不可变提交引用）

- **参考来源**：lakeFS 提交用内容寻址 ID，相同内容去重、可校验。
- **现状 gap**：`_build_snapshot` 的 `snapshot_id` 是确定性路径 `datasets/{version.id}/snapshot.json`（`services/datasets.py:1131`），非内容指纹。
- **改造内容**：写快照前对 manifest 内容算 sha256，对象键改为 `datasets/{version.id}/snapshot-{sha256[:16]}.json`（或保留原键 + 在 `quality/snapshot_id` 记 hash）。**注意**：影响对象键契约与既有快照兼容，需评估后再定升级策略。
- **涉及文件**：`backend/app/services/datasets.py::_build_snapshot`、`docs/OSS存储设计.md`。
- **验收**：相同内容重建快照得到相同 hash；对象键含内容指纹；既有快照读取路径兼容。

#### [DM-09]（可选）训练前自动建"实验快照"版本（lakeFS branch-per-experiment）

- **参考来源**：lakeFS branch-per-experiment——实验不污染主数据。
- **现状 gap**：训练引用现成 `dataset_version`，无"训练即隔离快照"语义。
- **改造内容**：评估后做——训练创建时若需要隔离，自动 `create_version` + 构建任务（复用 `create_auto_build_task` 模式，`services/datasets.py:466`），训练引用该实验版本，保证实验可回放不污染当前快照。
- **涉及文件**：`backend/app/api/v1/models.py`（training-tasks 创建）、`backend/app/services/models.py`。
- **验收**：训练创建即产出一个可追溯的实验版本，训练记录引用它。

#### [DM-11] 信号预览多级抽稀金字塔（缩放即时出图）

- **参考来源**：Grafana / TimescaleDB continuous aggregates（多级降采样预计算）；FiftyOne 服务端投影。
- **现状 gap**：`signals.downsample_indices` 是单级 min-max 抽稀（按 `max_points` 现算），缩放/平移每次按目标点数重算，中间尺度重复计算（910k 点单级 ~300ms 尚可，高频交互可感知）。
- **改造内容**：
  1. 信号导入成功（Parquet 落盘）或首次预览时，预计算 1/10、1/100、1/1000 三级 min-max 降采样金字塔，随 Parquet 一并缓存（复用 `signal_ingest._cached_parquet` LRU 思路）。
  2. `/signals` 预览按当前视口宽度选最近一级金字塔再细化，多数请求不再全量重算。
- **涉及文件**：`backend/app/services/signals.py`、`backend/app/services/signal_ingest.py`、`backend/app/api/v1/analysis.py`（signals 端点）。
- **验收**：同一视口第二次请求命中缓存；各级金字塔对瞬态尖峰（min-max 边界）均保留。

---

## 三、明确不做（边界）

1. **不引入** FiftyOne / Datumaro / lakeFS / Pachyderm 任一作为运行依赖或基础设施。三者思想均可用现有 DB + MinIO + 前端落地；只有 DM-07 可用"薄转换器"借用 Datumaro 思路，也不做常驻依赖。（此即 §零 迁移路线总原则的具体化，做任何 DM 任务前先读 §零。）
2. **不把数据集模型改成目录式**。当前 DB 固定快照（`dataset_versions + dataset_items`）是业务平台正确的形态，比 Datumaro 目录式更适合本系统。
3. **不做完整 Git 语义**（分支/合并/cherry-pick/回放）。lakeFS 只借"不可变提交 + 按引用可复现 + 回滚"三点。
4. **不做 FiftyOne 特色但超需求的**：embeddings 可视化、模型评估面板、dataset zoo。
5. **不引入独立数据流水线编排**（Pachyderm 定位），现有 Job 执行器（DB 轮询 + handler 注册表）已够。

## 四、实施顺序建议

1. **P0 先做（后端优先）**：DM-02（训练可复现，MLflow 已有基础，改动最小）→ DM-03（构建质量 + 划分类别平衡，直接影响训练质量，`run_build` 一处）→ DM-01（标签分布 UI，纯前端）。
2. **P1**：DM-04（成员筛选增强）→ DM-05（版本回滚）→ DM-06（缩略图叠加）→ DM-10（成员列表 keyset 分页；成员规模上来后建议提前到与 DM-04 同批做）。
3. **P2 按需**：DM-07（格式打通）→ DM-08（快照哈希）→ DM-09（实验快照）→ DM-11（信号多级抽稀金字塔）。

## 五、契约与文档影响（每项改动必须同步）

| 任务 | 契约/文档影响 |
|---|---|
| DM-02 | 无接口/表改动；`backend/app/integrations/CLAUDE.md` 补 `record_training` 行为 |
| DM-03 | `dataset_versions.quality` JSON 结构扩展 → 回写 `docs/数据库设计.md` §3.15 说明 |
| DM-04 | items 端点新参数 → 回写 `docs/API接口清单.md` §3.5 |
| DM-05 | 新端点 → 回写 `docs/API接口清单.md` §3.5 |
| DM-06 | 无接口改动 |
| DM-07 | export format 参数 → 回写 `docs/API接口清单.md` §3.4 |
| DM-08 | 对象键升级 → 回写 `docs/OSS存储设计.md`；评估既有快照兼容 |
| DM-09 | training-tasks 行为 → 回写 `docs/API接口清单.md` §3.6 |
| DM-10 | items 端点新增可选 cursor 参数（page/page_size 兼容保留）→ 回写 `docs/API接口清单.md` §3.5 |
| DM-11 | `/signals` 无接口改动；`signals.py`/`signal_ingest.py` 行为补充 → 同步 `backend/app/services/CLAUDE.md` |

> 通用规则：改动任何接口/表/对象键，须同步 `API接口清单.md` / `数据库设计.md` / `OSS存储设计.md` 三份契约 + 两端代码 + 涉及目录的 CLAUDE.md，再 commit。
