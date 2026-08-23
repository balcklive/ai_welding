# OSS 对象存储设计 — 焊接数据智能分析与 AI 建模平台

> 版本：v0.1（设计稿） · 日期：2026-08-23 · 状态：待实现
>
> 对象存储：**MinIO**（S3 兼容，远程服务，连接见 `.env`）。用于承载视频、图片、时序信号等**多模态大文件**；数据库只存元数据与对象键。

---

## 1. 设计决策

| 决策点 | 结论 |
|---|---|
| 桶 | 单桶 `aiwelding` + **前缀体系**分目录（避免多桶管理成本，前缀即"目录"） |
| 对象键 | 不可变、可读：`{前缀}/{业务标识}/{文件名}`；文件名规范化（小写、去空格、限长） |
| 访问 | **桶不公开**，全部经后端签发**预签名 URL**；数据库只存 `object_key`，不存公开 URL |
| 上传 | 小文件（<100MB）后端代理转发；**大文件（≥100MB，登记原始文件 ≤2GB）预签名直传**（不经过后端内存） |
| 下载/播放 | 预签名 GET URL + HTTP `Range` 支持（视频拖动播放）；默认有效期 1h |
| 生命周期 | 按前缀配置保留策略；启用版本化（可选）防误删 |
| 一致性 | `object_key` 与 `docs/数据库设计.md` 的 `object_keys`/`file_key`/`snapshot_id` 字段对接 |

## 2. 桶与对象键（Key）设计

```
aiwelding/  (桶)
├── raw/{registration_no}/{original_filename}          # 原始采集数据（登记上传）
├── processed/{weld_id}/
│   ├── align/{asset}                                  # 对齐产物（视频/轨道）
│   ├── split/{sample_key}.jpg | .npy                  # 切分样本（图像/信号）
│   └── signals/{channel}.csv                          # 信号片段
├── features/{extraction_id}.npy | .json               # 特征向量导出
├── annotations/{annotation_task_id}/export.json       # 标注导出
├── datasets/{dataset_version_id}/{snapshot}.json      # 数据集固定快照清单
├── models/{model_version_id}/weights.pt               # 模型权重
└── reports/{report_type}/{ref_id}.pdf                 # 导出报告
```

**对象键命名规则：**
- 层级：`{类型前缀}/{业务标识}/{文件名}`，如 `raw/REG-20260815-00248/0001.mp4`
- 业务标识用数据库业务列：`registration_no`、`weld_id`、`dataset_version_id`、`model_version_id`、`extraction_id`、`annotation_task_id`、`job_uid`
- 文件名：小写、空格转 `_`、去特殊字符、长度 ≤ 255，避免中文文件名直接落盘（可由上传服务生成规范化名）
- 每个对象键**全局唯一且不可变**；重传生成新 key，不回写旧 key

## 3. 上传流程

### 3.1 小文件（< 100MB）—— 后端代理
```
前端 ──POST /api/v1/files/upload──▶ FastAPI（流式） ──▶ MinIO ──▶ 返回 { object_key, url }
```
- 后端用流式（stream）转发，不整文件载入内存。
- 上传时写入对象元数据：`content-type`、`size`、`md5`；`object_key` 落库。

### 3.2 大文件（≥ 100MB / ≤ 2GB）—— 预签名直传（API 清单扩展点）
```
前端 ──POST /api/v1/files/presign-upload {size, content_type, prefix}──▶ 返回 { object_key, upload_url }
前端 ──PUT 直传 MinIO（upload_url）──▶ 完成回执
```
- 新增端点：`POST /api/v1/files/presign-upload`（**这是对 `API接口清单.md` 的补充扩展**）。
- 后端生成预签名 PUT URL（默认 30 分钟有效、指定 `Content-Length`），前端直接 PUT 到 MinIO，超大文件走 **multipart**。
- 直传避免 2GB 文件占用后端内存/带宽，登记页"单文件 ≤2GB"由后端校验 `Content-Length` 实现。

## 4. 下载与播放

- `GET /api/v1/files/{object_key}/url` → 后端校验登录/权限后签发**预签名 GET URL**（默认 1h，`?expires=` 可调）。
- **视频播放**：预签名 URL 支持 HTTP `Range`（拖动进度、倍速）；长视频可用更长有效期（如 24h）的流式 URL。
- **图片预览**：同预签名 URL；缩略图可在前端按需生成或由上传时生成（预留 `thumb` 前缀）。
- 所有访问均经后端鉴权，**不做公开读**。

## 5. 安全

| 项 | 策略 |
|---|---|
| 桶策略 | 默认私有，无公共读/写 |
| 访问 | 全部预签名 URL，有效期短、可吊销 |
| 传输 | MinIO 侧 http（当前 `.env` `MINIO_SECURE=false`）；生产如走公网建议开启 TLS |
| 敏感文件 | 原始视频/信号属敏感资产，只允许授权用户（当前最小认证=登录即可）获取预签名 |
| 防篡改 | 上传时记录 `md5`，下载可校验（可选） |

## 6. 生命周期与容量

| 前缀 | 保留策略 | 说明 |
|---|---|---|
| `raw/` | 按版本归档规则（如 180 天） | 原始数据，登记后即版本链 v1.0 |
| `processed/` | 任务完成后默认保留，可清理 | 对齐/切分中间产物 |
| `features/` | 长期保留 | 特征向量可复现 |
| `datasets/` | 长期保留（对应固定快照） | 数据集版本可复现 |
| `models/` | 长期保留 | 模型版本权重 |
| `reports/` | 30 天 | 导出报告 |
| `annotations/` | 长期保留 | 标注导出 |

- 启用 MinIO **桶版本化**（可选）：防误删，回滚旧对象。
- 容量告警：按桶/前缀统计大小，超阈值告警（预留运维项）。

## 7. 与接口/数据库的对接

| 位置 | 对接点 |
|---|---|
| API | `POST /files/upload`、`GET /files/{key}/url`（清单 §3.7）；`POST /files/presign-upload`（本文档扩展） |
| 数据库 | `data_versions.object_keys`（v1.0 原始文件）、`samples.object_keys`、`model_versions.file_key`、`dataset_versions.snapshot_id`、`inference_tasks.input_key` 存的就是本文档的对象键 |
| 登记上传 | 登记表单的原始文件 → `raw/{registration_no}/...`；上传后经 `POST /registrations/{id}/raw-files` 把 object_key 挂到 v1.0 原始数据版本（存 `data_versions.object_keys`） |

> 一致性：所有对象键一律以本文档前缀体系为准；数据库字段与接口参数只引用 `object_key` 字符串。
