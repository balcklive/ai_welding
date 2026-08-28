# CLAUDE.md — docs/

项目文档目录，无脚本。

实现状态：**四份契约文档与后端/前端均已实现，本地跑通**（pytest 全绿、`npm run build` 通过）；契约与实现之间的偏差已回写本文档（见下方"已回写差异"），以契约文档 + 实际代码为准。

- `API接口清单.md`：前后端 API 接口清单（v0.1，已实现）。Task 2–4 追加数据集版本成员 `GET /datasets/{dataset_id}/versions/{version_id}/items` 的 `Page<DatasetItemRow>` 契约和前端映射；成员必须来自 `dataset_items` 固定快照，不能回退为全局焊缝前端过滤。覆盖四个模块全部页面功能 → 后端接口（`/api/v1`）→ 前端接口（`src/api/`）的完整映射；含全局约定（认证/响应信封/分页/异步 Job/文件存储）。
- `数据库设计.md`：MySQL 表结构（23 张表：字段/约束/索引/ER 关系）+ 版本与数据集快照逻辑，对应 API 清单实体。
- `OSS存储设计.md`：MinIO 对象存储（单桶 + 前缀键体系、小文件代理/大文件预签名直传、访问控制、生命周期）。
- `文件与目录设计.md`：目录结构设计（后端独立 `backend/`、前端留根）+ 前后端接口文件对应表 + 命名与部署规则。
- `开发规范.md`：**实际编码必守原则**——复用优先（含复用清单与刻意不复用的项）、接口调用轮转日志规范、已确认的实施边界（真实 DSP + 模拟重算 / 最小侵入接线 / 本地跑通 / 自动 seed）。
- `真实数据准备与导入.md`：给数据/工艺工程师的**真实数据导入指南**——每模态文件格式与命名、元数据字段、对象键约定、界面 + API 导入流程、与演示数据切换、以及"分析/训练为模拟结果"的架构限制说明。
- `破坏性测试指导.md`：**网页端破坏性/健壮性测试手册**——准备清单（备份/环境）、分轮次测试矩阵（鉴权/注入/上传/CSV 导入/并发/负载/前端容错）、日志取证判定、恢复步骤、已知风险点；配套测试数据包见 `backend/tests/fixtures/destructive/`。
- `功能验证测试清单.md`：**业务功能验证总清单**——在真实数据上传、核验和检测已跑通后，继续覆盖版本、对齐、切分、标注、特征、数据集、模型、报告、对象存储、审计、鉴权、异常、边界、并发和负载测试；每项包含编号、操作目标、通过标准和当前模拟实现边界。
- `真实数据端到端走通记录.md`：**真实数据全流程走通实录**（登记→上传→信号导入→核验→分析，2026-08-25）——每步接口与结果、两个数据适配发现（time 列数值秒、量程放宽）、`detect_events` 阈值自适应 + 边界伪异常修复、复现方法与边界。

坑/限制：
- Task 2–4 的页面层级固定为 数据集概览 → 当前版本成员 → 成员详情；数据中心不再提供独立全局数据列表入口，成员详情仍通过 `selectedDataId` 进入既有核验/版本/分析流。
- 契约文档当前为"已实现"基准（Task 1~24 已完成，本地跑通）；改动任何接口/表/对象键，仍须按本文件规则同步三份契约 + 两端代码。
- **已回写差异（Task 25）**：① `POST /registrations/{id}/raw-files` 请求体新增可选 `storage_bytes`（缺省 0）；② `POST /files/presign-upload` 请求体新增可选 `filename`（缺省 `"file"`）；③ `GET /welds` 筛选映射说明（`tab=已归档`→`quality=='通过'`、`tab=最近`=created_at desc、`brand`→`machine` 前缀）；④ `DataVersion` 前端以 `record_id` 关联、`Project` 无 `id` 字段；⑤ `exportReport` 返回 `{urls:[{ref_id,url}]}`、`login` 返回含 `token_type`、`createDatasetVersion` 的 `name` 可选；⑥ `POST /datasets/{id}/versions` 的 `name`/`note` 与 `POST /datasets` 的 `source` 接受但不落库（表无列）；⑦ `数据库设计.md` §4 记录 `training_tasks.base_model_id` 无索引（与"所有任务表 FK 列均建索引"矛盾的既有设计）；⑧ `开发规范.md` §1.1 补"分页自写 `paginate()` helper"刻意不复用项。
- **已回写差异（标注 kind 升级，2026-08-27）**：`annotations` 表新增 `kind`（box/segment/polygon）、`points`、`start_time`、`end_time` 四列（见 `数据库设计.md` §3.11 与计划 `docs/superpowers/plans/2026-08-27-annotation-kinds.md`）；`POST …/labels` 的 `LabelItem` 支持按 `kind` 分支校验（box 四元组 / segment 时间区间 / polygon 顶点），现有 bbox 标注与老数据兼容。
- **已回写差异（标注 P2/P3，2026-08-28）**：① `label_categories` 新增"熔池"类别（共 6 类，视频语义分割单类）；② `POST /annotation-tasks` source 新增 `signal`/`video`（均需 `version_id`，同步生成 `meta.mode='signal'/'video'` 锚点样本，video 锚点含 `video_key`）；③ 新增 `POST /annotation-tasks/{id}/frames`（视频帧锚点，body 含 `timestamp`/`frame_width?`/`frame_height?`）；④ 新增 `POST /annotation-tasks/{id}/export`（P3：video → 帧图+掩膜 PNG，signal → segment JSON，写 `processed/{weld_id}/annotate/`）；⑤ 前端新增 `react-image-annotate@1.8.0`（peer 仅 React 16，`--legacy-peer-deps` 安装，非受控组件走 `onExit`）与后端 `pillow` 依赖。
- 三份契约强相关：改接口需同步 `API接口清单.md` + `数据库设计.md`（表/字段）+ `OSS存储设计.md`（对象键）+ 两端代码。
- `POST /files/presign-upload` 为 OSS 设计补充的扩展端点（大文件直传），已回写进 `API接口清单.md`。
- 登记原始文件挂载（`POST /registrations/{id}/raw-files` → `data_versions.object_keys`、`data_records.storage_bytes`）与标注任务（`POST /annotation-tasks` + `annotation_tasks` 表，`jobs.type` 含 annotation）是为覆盖前端功能补齐的修订，改动时勿删。
- **版本与模型生命周期补齐**（勿删）：版本由 `POST /welds/{id}/versions`（去噪/人工修正）、对齐任务成功（时间对齐版本）、`POST /registrations`（v1.0）产生；`data_records` 新增 `weld_name`；对齐产物对象键存 `alignment_tasks.assets`；数据集质量存 `dataset_versions.quality`；模型由 `POST /models` 新建、训练成功自动生成 `model_versions`、`PATCH /models/{id}/versions/{vid}` 流转状态；推理输入走 `uploads/` 临时前缀；`reports/export` type 含 `data-list`。
- **两套缺陷词表**：总览"缺陷分布"为统计口径（可含未焊透/焊穿/夹渣等），标注"标签类别"为模型口径（焊瘤/气孔/未熔合/咬边/正常），勿混用。
- `开发规范.md` 为实施原则（必守），实现后端/前端时与三份契约并列依据：契约定"是什么"，该文档定"怎么实现、按什么原则实现"。
