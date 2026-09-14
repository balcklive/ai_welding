# CLAUDE.md — docs/

项目文档目录，无脚本。

实现状态：**四份契约文档与后端/前端均已实现，本地跑通**（pytest 全绿、`npm run build` 通过）；契约与实现之间的偏差已回写本文档（见下方"已回写差异"），以契约文档 + 实际代码为准。

- `API接口清单.md`：前后端 API 接口清单（v0.1，已实现）。Task 2–4 追加数据集版本成员 `GET /datasets/{dataset_id}/versions/{version_id}/items` 的 `Page<DatasetItemRow>` 契约和前端映射；成员必须来自 `dataset_items` 固定快照，不能回退为全局焊缝前端过滤。覆盖四个模块全部页面功能 → 后端接口（`/api/v1`）→ 前端接口（`src/api/`）的完整映射；含全局约定（认证/响应信封/分页/异步 Job/文件存储）。
- `数据库设计.md`：MySQL 表结构（26 张表：字段/约束/索引/ER 关系，含 `signal_ingests` / `annotation_ls_sync` / 2026-09 新增 `option_items`）+ 版本与数据集快照逻辑，对应 API 清单实体。
- `OSS存储设计.md`：MinIO 对象存储（单桶 + 前缀键体系、小文件代理/大文件预签名直传、访问控制、生命周期）。
- `文件与目录设计.md`：目录结构设计（后端独立 `backend/`、前端留根）+ 前后端接口文件对应表 + 命名与部署规则。
- `开发规范.md`：**实际编码必守原则**——复用优先（含复用清单与刻意不复用的项）、接口调用轮转日志规范、已确认的实施边界（真实 DSP + 模拟重算 / 最小侵入接线 / 本地跑通 / 自动 seed）。
- `真实数据准备与导入.md`：给数据/工艺工程师的**真实数据导入指南**——每模态文件格式与命名、元数据字段、对象键约定、界面 + API 导入流程、与演示数据切换，以及真实信号/对齐能力与部分算法模拟结果的架构边界说明。
- `破坏性测试指导.md`：**网页端破坏性/健壮性测试手册**——准备清单（备份/环境）、分轮次测试矩阵（鉴权/注入/上传/CSV 导入/并发/负载/前端容错）、日志取证判定、恢复步骤、已知风险点；配套测试数据包见 `backend/tests/fixtures/destructive/`。
- `功能验证测试清单.md`：**业务功能验证总清单**——在真实数据登记、核验和检测已跑通后，继续覆盖版本、对齐、切分、标注、特征、数据集、模型、报告、对象存储、审计、鉴权、异常、边界、并发和负载测试；每项包含编号、操作目标、通过标准和当前模拟实现边界。
- `工程大文件切割方案.md`：**大文件切割方案**——前端批次（App/features/CSS）已完成（`App.tsx` 收敛至 ~138 行）；后端批次（analysis/datasets/welds 大文件拆分）未执行，见文档 §6。
- `业务流程与产品体验验收测试计划.md`：**业务流程与产品体验验收测试计划**（平台业务闭环 + 产品/UI 评估 + 增量回归，原 `Playwright菜单功能测试计划.md`，2026-08-29 改名与内容对齐）——待执行。
- `机器学习平台集成进展与方向.md`：**机器学习平台扩展集成进展与方向**（2026-09-05）——compose 多服务部署（LS+MLflow+app）、镜像 mirror、LS 标注模板项目 id 3/4/5、LS/MLflow 鉴权备忘、后续方向（LS 适配层 / DM P0 / MLflow Phase2 / 安全收敛 / 长期吸收进主应用）。上游设计见 `superpowers/specs/2026-09-05-mlflow-dataset-annotation-design.md`。
- `使用手册.md`：**面向最终用户的项目使用手册**（介绍为主）——项目简介、整体业务流程、四大模块逐页功能说明（嵌入 `images/manual/` 下 19 张 Playwright 实机截图）、全局使用约定与系统能力边界。配套交付版 `使用手册.docx` / `使用手册.pdf`（由 `使用手册.html` 经 pypandoc + Chromium 打印生成，改 md 后需重新导出）。
- `images/manual/`：使用手册全部页面截图（00-login 至 18-inference，1600×900 视口，Playwright CLI 截取，登录账号走本地 dev 服务）。
- `特征提取发布门禁.md`：**特征提取第二阶段发布门禁**——发布前运行 `scripts/feature_release_gate.py`，含视觉服务/连接探测/seed 关闭/PT 导出/前后端门禁验收清单，尚未执行。
- `数据管理体验评估与问题清单.md`：**数据管理模块的体验评估与问题清单**（2026-09-14）——Q1–Q21 问答 + S1–S12 问题项的原始记录，已由开发人员逐题作答。**保留为原始问答记录，不再更新**；结论与执行口径以 `数据管理改造技术实施方案.md` 为准。
- `数据管理改造技术实施方案.md`：**数据管理改造的唯一事实来源**（2026-09-14，适用 `bdcbd30`）——术语基线（样本 / 数据版本 / 切片）、一期 T1–T11 + T16、二期 T13–T15、三期 roadmap，含决策 D1–D20、数据库与接口变更清单、风险与验收。**已做过一轮静态代码核对**：修正了 10 处与代码现状不符的判断（质量指标口径、构建成员来源、冻结程度、异步状态出口、登记状态机、切分影响面、分页消费者、错误契约、删除引用矩阵、产物版本指针），各任务末尾的"代码依据"给出核对位置。**代码尚未开工**；改动接口/表结构时需同步本文档 + 三份契约。

坑/限制：
- Task 2–4 的页面层级固定为 数据集概览 → 当前版本成员 → 成员详情；数据管理不再提供独立全局数据列表入口，成员详情仍通过 `selectedDataId` 进入既有核验/版本/分析流。
- 契约文档当前为"已实现"基准（Task 1~24 已完成，本地跑通）；改动任何接口/表/对象键，仍须按本文件规则同步三份契约 + 两端代码。
- **已回写差异（Task 25）**：① `POST /registrations/{id}/raw-files` 请求体新增可选 `storage_bytes`（缺省 0）；② `POST /files/presign-upload` 请求体新增可选 `filename`（缺省 `"file"`）；③ `GET /welds` 筛选映射说明（`tab=已归档`→`quality=='通过'`、`tab=最近`=created_at desc、`brand`→`machine` 前缀）；④ `DataVersion` 前端以 `record_id` 关联（`Project` 类型已于 2026-09-14 随总览数据集卡片删除）；⑤ `exportReport` 返回 `{urls:[{ref_id,url}]}`、`login` 返回含 `token_type`、`createDatasetVersion` 的 `name` 可选；⑥ `POST /datasets/{id}/versions` 的 `name`/`note` 与 `POST /datasets` 的 `source` 接受但不落库（表无列）；⑦ `数据库设计.md` §4 记录 `training_tasks.base_model_id` 无索引（与"所有任务表 FK 列均建索引"矛盾的既有设计）；⑧ `开发规范.md` §1.1 补"分页自写 `paginate()` helper"刻意不复用项。
- **已回写差异（标注 kind 升级，2026-08-27）**：`annotations` 表新增 `kind`（box/segment/polygon）、`points`、`start_time`、`end_time` 四列（见 `数据库设计.md` §3.11 与迁移 `0007`）；`POST …/labels` 的 `LabelItem` 支持按 `kind` 分支校验（box 四元组 / segment 时间区间 / polygon 顶点），现有 bbox 标注与老数据兼容。
- **已回写差异（标注 P2/P3，2026-08-28）**：① `label_categories` 新增"熔池"类别（共 6 类，视频语义分割单类）；② `POST /annotation-tasks` source 新增 `signal`/`video`（均需 `version_id`，同步生成 `meta.mode='signal'/'video'` 锚点样本，video 锚点含 `video_key`）；③ 新增 `POST /annotation-tasks/{id}/frames`（视频帧锚点，body 含 `timestamp`/`frame_width?`/`frame_height?`）；④ 新增 `POST /annotation-tasks/{id}/export`（P3：video → 帧图+掩膜 PNG，signal → segment JSON，写 `processed/{weld_id}/annotate/`）；⑤ 前端新增 `react-image-annotate@1.8.0`（peer 仅 React 16，`--legacy-peer-deps` 安装，非受控组件走 `onExit`）与后端 `pillow` 依赖。
- **已回写差异（多模态数据字段，2026-09-05）**：① `data_records` 新增 `wire_feed_speed`/`welding_speed`（单值工艺参数，登记可填/CSV 导入稳态回填）与 `data_fields`（JSON 字段概览），迁移 `0012`；② `signal_ingest` 全列动态导入（Parquet schema_version=2，核心 4 + 扩展通道 `weld_speed`/`j1..j6`/`pool_*` + 自动保留数值列），`/signals` 不带 `channels` 即返回全部分量；③ 电压量程放宽至 0–700V（兼容客户 `data/多模态分析.csv`）。登记表单/数据详情/源记录表/波形预览按此扩展，详见 `数据库设计.md` §3.2、`API接口清单.md` §3.3/3.4、`真实数据准备与导入.md` §2.3。
- **已回写差异（LS 集成，2026-09-06）**：① `label_categories` 补第 6 类「熔池」（迁移 `0014`，决策 4）；② `annotation_tasks` 新增 `ls_status`（默认 `legacy`，迁移 `0013`）；③ 新表 `annotation_ls_sync`（§3.25，`(annotation_task_id, sample_id)` 幂等）。LS region 类型实为 `rectanglelabels`/`polygonlabels`/`timeserieslabels`（非 `rectangle`/`polygon`），坐标 0-100% 以 `original_width/height` 换算像素（见 `backend/app/integrations/labelstudio.py::convert_region`）；训练折叠用缺陷白名单排除熔池（决策 6）。后端集成已对真实 LS+MySQL+MinIO 走通 e2e（`backend/scripts/premise_validation/e2e_ls_roundtrip.py`）。**模态集成现状（2026-09-06）**：仅**图像**端到端可走 LS（bbox→项目3，闭环验通）；**视频(项目4)/时序(项目5)媒体未导出**（锚点/帧/信号样本无 `object_keys` → 不推 LS），暂走主应用自研画布过渡——下一步已列入计划文档轨道 A（抽帧图片→项目4 / 时序 CSV→项目5）。
- **已回写差异（系统设置·可选项字典，2026-09-14）**：① 新表 `option_items`（§3.26，`group_key` 分组 + UK `(group_key,value)` + `active` 软删 + `sort_order`，承载 machine/weld_method/source/product/dataset_task）；② `label_categories` 补 `sort_order`/`active`（§3.12，标注类别仍落本表不搬家）；③ 新接口 `GET/POST/PATCH/DELETE /settings/options`（契约 §3.8，写操作仅管理员，删除按业务引用软删/物理删）；④ 前端新增 `features/settings`（侧边栏「系统设置」→ 路由 `settings`）与 `api/settings.ts`，数据登记/数据集新建改读字典。迁移 `0015`。原「系统设置暂无对应页面」的预留说明已更新（仅通用键值 `PUT /settings` 仍预留）。
- 三份契约强相关：改接口需同步 `API接口清单.md` + `数据库设计.md`（表/字段）+ `OSS存储设计.md`（对象键）+ 两端代码。
- `POST /files/presign-upload` 为 OSS 设计补充的扩展端点（大文件直传），已回写进 `API接口清单.md`。
- 登记原始文件挂载（`POST /registrations/{id}/raw-files` → `data_versions.object_keys`、`data_records.storage_bytes`）与标注任务（`POST /annotation-tasks` + `annotation_tasks` 表，`jobs.type` 含 annotation）是为覆盖前端功能补齐的修订，改动时勿删。
- **版本与模型生命周期补齐**（勿删）：版本由 `POST /welds/{id}/versions`（去噪/人工修正）、对齐任务成功（时间对齐版本）、`POST /registrations`（v1.0）产生；`data_records` 新增 `weld_name`；对齐产物对象键存 `alignment_tasks.assets`；数据集质量存 `dataset_versions.quality`；模型由 `POST /models` 新建、训练成功自动生成 `model_versions`、`PATCH /models/{id}/versions/{vid}` 流转状态；推理输入走 `uploads/` 临时前缀；`reports/export` type 含 `data-list`。
- **两套缺陷词表**：总览"缺陷分布"为统计口径（可含未焊透/焊穿/夹渣等），标注"标签类别"为模型口径（焊瘤/气孔/未熔合/咬边/正常），勿混用。
- `开发规范.md` 为实施原则（必守），实现后端/前端时与三份契约并列依据：契约定"是什么"，该文档定"怎么实现、按什么原则实现"。
