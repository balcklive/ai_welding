# CLAUDE.md — docs/

项目文档目录，无脚本。

- `API接口清单.md`：前后端 API 接口清单（设计稿 v0.1）。覆盖四个模块全部页面功能 → 后端接口（`/api/v1`）→ 前端接口（`src/api/`）的完整映射；含全局约定（认证/响应信封/分页/异步 Job/文件存储）。
- `数据库设计.md`：MySQL 表结构（23 张表：字段/约束/索引/ER 关系）+ 版本与数据集快照逻辑，对应 API 清单实体。
- `OSS存储设计.md`：MinIO 对象存储（单桶 + 前缀键体系、小文件代理/大文件预签名直传、访问控制、生命周期）。
- `文件与目录设计.md`：目录结构设计（后端独立 `backend/`、前端留根）+ 前后端接口文件对应表 + 命名与部署规则。
- `开发规范.md`：**实际编码必守原则**——复用优先（含复用清单与刻意不复用的项）、接口调用轮转日志规范、已确认的实施边界（真实 DSP + 模拟重算 / 最小侵入接线 / 本地跑通 / 自动 seed）。

坑/限制：
- 四份文档均为设计稿，尚未实现；实现后端/前端接口层时以它们为契约基准。
- 三份契约强相关：改接口需同步 `API接口清单.md` + `数据库设计.md`（表/字段）+ `OSS存储设计.md`（对象键）+ 两端代码。
- `POST /files/presign-upload` 为 OSS 设计补充的扩展端点（大文件直传），已回写进 `API接口清单.md`。
- 登记原始文件挂载（`POST /registrations/{id}/raw-files` → `data_versions.object_keys`、`data_records.storage_bytes`）与标注任务（`POST /annotation-tasks` + `annotation_tasks` 表，`jobs.type` 含 annotation）是为覆盖前端功能补齐的修订，改动时勿删。
- **版本与模型生命周期补齐**（勿删）：版本由 `POST /welds/{id}/versions`（去噪/人工修正）、对齐任务成功（时间对齐版本）、`POST /registrations`（v1.0）产生；`data_records` 新增 `weld_name`；对齐产物对象键存 `alignment_tasks.assets`；数据集质量存 `dataset_versions.quality`；模型由 `POST /models` 新建、训练成功自动生成 `model_versions`、`PATCH /models/{id}/versions/{vid}` 流转状态；推理输入走 `uploads/` 临时前缀；`reports/export` type 含 `data-list`。
- **两套缺陷词表**：总览"缺陷分布"为统计口径（可含未焊透/焊穿/夹渣等），标注"标签类别"为模型口径（焊瘤/气孔/未熔合/咬边/正常），勿混用。
- `开发规范.md` 为实施原则（必守），实现后端/前端时与三份契约并列依据：契约定"是什么"，该文档定"怎么实现、按什么原则实现"。
