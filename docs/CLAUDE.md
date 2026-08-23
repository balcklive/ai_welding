# CLAUDE.md — docs/

项目文档目录，无脚本。

- `API接口清单.md`：前后端 API 接口清单（设计稿 v0.1）。覆盖四个模块全部页面功能 → 后端接口（`/api/v1`）→ 前端接口（`src/api/`）的完整映射；含全局约定（认证/响应信封/分页/异步 Job/文件存储）。
- `数据库设计.md`：MySQL 表结构（23 张表：字段/约束/索引/ER 关系）+ 版本与数据集快照逻辑，对应 API 清单实体。
- `OSS存储设计.md`：MinIO 对象存储（单桶 + 前缀键体系、小文件代理/大文件预签名直传、访问控制、生命周期）。
- `文件与目录设计.md`：目录结构设计（后端独立 `backend/`、前端留根）+ 前后端接口文件对应表 + 命名与部署规则。

坑/限制：
- 四份文档均为设计稿，尚未实现；实现后端/前端接口层时以它们为契约基准。
- 三份契约强相关：改接口需同步 `API接口清单.md` + `数据库设计.md`（表/字段）+ `OSS存储设计.md`（对象键）+ 两端代码。
- `POST /files/presign-upload` 为 OSS 设计补充的扩展端点（大文件直传），已回写进 `API接口清单.md`。
- 登记原始文件挂载（`POST /registrations/{id}/raw-files` → `data_versions.object_keys`、`data_records.storage_bytes`）与标注任务（`POST /annotation-tasks` + `annotation_tasks` 表，`jobs.type` 含 annotation）是为覆盖前端功能补齐的修订，改动时勿删。
