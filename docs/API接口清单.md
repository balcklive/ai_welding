# API 接口清单 — 焊接数据智能分析与 AI 建模平台

> 版本：v0.1（设计稿） · 日期：2026-08-23 · 状态：待实现
>
> 目标：本文档中的接口**完整支撑现有前端静态页面的全部功能**。后端采用 FastAPI + MySQL + MinIO（连接配置见 `.env`），前端通过 `src/api/` 调用，一律相对路径 `/api/v1/...`。

---

## 目录

1. [全局约定](#1-全局约定)
2. [核心实体](#2-核心实体)
3. [后端接口清单](#3-后端接口清单)
4. [前端接口层](#4-前端接口层)
5. [功能覆盖对照表](#5-功能覆盖对照表)
6. [附录](#6-附录)

---

## 1. 全局约定

### 1.1 基础与命名
- 所有接口前缀：`/api/v1`（后端注册在 `backend/app/api/v1/`）。
- 资源命名一律复数（`/welds`、`/datasets`）；层级用嵌套表达归属（`/welds/{weld_id}/versions`）。
- 前端调用走相对路径，开发环境由 Vite proxy 转发，生产环境同源，无需切换。

### 1.2 认证（最小）
- 仅登录 + JWT 校验，**暂不细分角色权限**。
- `POST /auth/login` → `{ access_token, token_type, user }`；`GET /auth/me` 用于刷新恢复会话（页面用户卡"林工/管理员"）。
- 业务接口携带 `Authorization: Bearer <JWT>`，文中统一标注 **需登录**。

### 1.3 响应与错误（统一信封）
- 成功：`{ "code": 0, "message": "ok", "data": <实际数据> }`
- 失败：`{ "code": <业务码>, "message": <可读信息>, "detail": <可选详情> }`，同时带 HTTP 状态码
- 前端用统一 `request()` 封装解包 `code`，非 0 自动提示错误。

| HTTP | 含义 |
|---|---|
| 400 | 参数错误 |
| 401 | 未登录 / 令牌失效 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 409 | 冲突（如重复登记编号、数据集版本冲突） |
| 422 | 参数校验失败 |
| 500 | 服务内部错误 |

### 1.4 分页与筛选
- 列表接口统一 `?page=1&page_size=20`（`page_size` 最大 100），响应：`{ "items": [], "total": 0, "page": 1, "page_size": 20 }`。
- **筛选一律服务端执行**：关键词、数据来源、焊机品牌、核验状态等作为 query 参数（遵守 README 既定规则，前端不做全量过滤）。

### 1.5 异步任务（统一 Job 模型）
- 重算接口（对齐 / 切分 / 数据集构建 / 训练 / 测试 / 推理）统一流程：
  `POST` 创建 → 返回 `{ job_id }` → 前端轮询状态。
- 统一状态结构：

```json
{
  "id": "job_xxx",
  "type": "training",
  "status": "pending | running | succeeded | failed",
  "progress": 0,
  "result": null,
  "error": null,
  "created_at": "2026-08-23T09:42:00Z",
  "finished_at": null
}
```

- 每个域有专属任务资源（`/training-tasks/{id}` 等），但返回体是同一套 Job 结构；前端只需一个 `useJob()` 轮询钩子 + `jobs.getJob()`。

### 1.6 文件存储（MinIO）
- 上传：`POST /files/upload`（multipart，单文件 ≤ 2GB，符合登记页约束）→ 存 MinIO，返回 `{ object_key, url }`。
- 播放/下载：`GET /files/{object_key}/url` → 返回短期预签名 URL（视频/图片流式播放，不经过后端内存）。
- 大文件对象（视频/图片/多模态信号）存储在 MinIO，数据库只存元数据与 `object_key`。

### 1.7 时间与标识
- 时间统一 ISO 8601（UTC）。
- 标识：焊缝 `WLD-YYYYMMDD-序号`、登记编号 `REG-YYYYMMDD-序号`、数据集 `DS-xxx-序号`、任务 `job_xxx` / `TR-...`。

---

## 2. 核心实体

| 实体 | 说明 | 关键字段 |
|---|---|---|
| `User` | 用户（暂不细分角色） | id, username, display_name, role, avatar |
| `DataRecord` | 焊缝数据登记（一条焊缝 = 一条记录） | id, weld_id, registration_no, source, collected_at, machine, weld_method, material, thickness, current_voltage, sample_rate, product, modalities, quality, latest_version_id |
| `DataVersion` | 数据版本（原始/去噪/对齐/人工修正…） | id, weld_id, version_no, action, operator, created_at, note |
| `ValidationReport` | 数据核验报告 | id, version_id, score, passed, warning, failed, duration, rules[] |
| `ValidationRule` | 核验规则结果（15 项） | name, status(passed/warning/failed), message |
| `AlignmentTask` | 多模态对齐任务（Job） | id, version_id, status, events{arc, weld_segment, tail}, tracks[] |
| `SplitTask` | 数据切分任务（Job） | id, version_id, status, rules, sample_count |
| `Sample` | 切分样本 | id, task_id, object_keys[], frame_no, annotations[] |
| `Annotation` | 标注结果 | sample_id, labels[{category, box, confidence}], annotator, updated_at |
| `LabelCategory` | 缺陷标签类别 | name（焊瘤/气孔/未熔合/咬边/正常） |
| `FeatureExtraction` | 特征提取结果 | id, version_id, ts_features, vision_features, audio_features, unified_vector{dims, groups}, normalization, format |
| `Dataset` | 数据集 | id, name, task, sample_count, progress, current_version, status(标注中/可训练) |
| `DatasetVersion` | 数据集版本（固定快照） | id, dataset_id, version_no, split{train/val/test}, item_count, snapshot_id |
| `DatasetItem` | 数据集版本成员（固定样本清单） | dataset_version_id, sample_id, split |
| `Model` | 模型仓库条目 | id, name, type, version, metric, status(生产候选/训练中/实验版本) |
| `TrainingTask` | 训练任务（Job） | id, dataset_version_id, base_model_id, hyperparams, metrics, loss_curve, logs |
| `TestTask` | 测试任务（Job） | id, model_version_id, dataset_version_id, tasks[], metrics, confusion_matrix |
| `InferenceTask` | 推理任务（Job） | id, model_version_id, input, result{boxes, categories, confidence, latency} |
| `Job` | 通用异步任务状态 | id, type, status, progress, result, error, created_at, finished_at |

---

## 3. 后端接口清单

### 3.1 🔐 auth 认证

| 方法 | 路径 | 功能 | 关键参数 / 请求体 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 登录，返回 JWT + 用户信息 | body: `{ username, password }` |
| GET | `/api/v1/auth/me` | 当前登录用户信息（刷新恢复会话） | — 需登录 |

### 3.2 📊 dashboard 数据总览

| 方法 | 路径 | 功能 | 关键参数 |
|---|---|---|---|
| GET | `/api/v1/dashboard/stats` | 统计卡：数据总量 / 厂商总量 / 最大容量 / 已标注样本+完成度 | 需登录 |
| GET | `/api/v1/dashboard/attributes` | 属性面板：焊机种类 / 缺陷种类 / 多模态种类 / 采集频率档位 | 需登录 |
| GET | `/api/v1/dashboard/distributions` | 分布图：厂商比重 / 过渡类型 / 焊接类型 / 缺陷分布 / 厂商词云 | 需登录 |
| GET | `/api/v1/dashboard/projects` | 数据项目卡片（名称/状态/样本数/标注进度/最近更新） | 需登录 |

### 3.3 🗂 welds 焊缝数据（列表 · 登记 · 版本 · 核验）

| 方法 | 路径 | 功能 | 关键参数 / 请求体 |
|---|---|---|---|
| GET | `/api/v1/welds` | 数据列表：服务端分页+筛选，按焊缝 ID 去重、仅最新版本 | query: `q`(关键词:焊缝ID/登记编号), `source`, `brand`, `status`(通过/待复核/异常), `tab`(全部最新/待核验/已归档), `page`, `page_size` |
| GET | `/api/v1/welds/{weld_id}` | 单条焊缝详情（来源/焊机/模态/核验状态/最新版本） | — 需登录 |
| POST | `/api/v1/registrations` | 新建数据登记，生成唯一登记编号 | body: `source`, `collected_at`, `weld_name`, `product`, `machine`, `weld_method`, `material`, `thickness`, `current_voltage`, `sample_rate` |
| GET | `/api/v1/registrations/{registration_id}` | 登记信息详情 | — 需登录 |
| PATCH | `/api/v1/registrations/{registration_id}` | 编辑当前选中数据的登记信息 | body 同 POST（部分字段可选） |
| GET | `/api/v1/welds/{weld_id}/versions` | 版本链（v1.0~v1.3 + 操作人/时间/动作） | — 需登录 |
| GET | `/api/v1/welds/{weld_id}/versions/{version_id}` | 单个版本详情 | — 需登录 |
| POST | `/api/v1/welds/{weld_id}/versions/{version_id}/validation` | 执行核验（同步，15 项规则），返回质量评分+通过/警告/失败计数 | — 需登录 |
| GET | `/api/v1/welds/{weld_id}/versions/{version_id}/validation` | 核验明细：每条规则状态与异常原因、核验时间/耗时 | — 需登录 |

### 3.4 🌊 analysis 分析与标注

| 方法 | 路径 | 功能 | 关键参数 / 请求体 |
|---|---|---|---|
| GET | `/api/v1/analysis/candidates` | 选择数据页：已登记且核验通过的可分析数据列表 | 需登录 |
| POST | `/api/v1/welds/{weld_id}/versions/{version_id}/alignment-tasks` | 提交多模态对齐任务（**异步**） | body: `modalities[]` |
| GET | `/api/v1/alignment-tasks/{task_id}` | 对齐任务状态/结果：时间轴、起弧/有效段/收弧事件、各模态轨道 | 轮询（Job 结构） |
| GET | `/api/v1/welds/{weld_id}/versions/{version_id}/signals` | 多通道时域波形（电流/电压/气体/送丝） | query: `channels[]`, `filter_type`(低通/高通/带通), `cutoff`, `cutoff2` |
| GET | `/api/v1/welds/{weld_id}/versions/{version_id}/analysis/{mode}` | 单视图分析数据：`mode` ∈ `psd\|stft\|dwt\|wavelet\|phase\|pdd` | query: `channel` |
| GET | `/api/v1/welds/{weld_id}/versions/{version_id}/analysis/result` | AI 异常检测结果：焊接稳定度、正常/电弧不稳/飞溅比例、异常区段列表 | — 需登录 |
| POST | `/api/v1/welds/{weld_id}/versions/{version_id}/split-tasks` | 提交数据切分任务（**异步**） | body: `fixed_rate`(帧/样本), `keep_event_buffer`(±s), `task_format`(目标检测/图像分类/语义分割/时序分类) |
| GET | `/api/v1/split-tasks/{task_id}` | 切分任务状态/结果（生成样本数） | 轮询（Job 结构） |
| GET | `/api/v1/label-categories` | 缺陷标签类别（焊瘤/气孔/未熔合/咬边/正常） | 需登录 |
| GET | `/api/v1/annotation-tasks/{task_id}/samples` | 标注样本列表（分页，如样本 0248/1209） | query: `page`, `page_size` |
| GET | `/api/v1/annotation-tasks/{task_id}/samples/{sample_id}` | 单个样本详情（图像/信号 + 现有标注） | — 需登录 |
| POST | `/api/v1/annotation-tasks/{task_id}/samples/{sample_id}/ai-pretag` | AI 预标注（同步）：返回疑似缺陷区域+置信度 | 需登录 |
| POST | `/api/v1/annotation-tasks/{task_id}/samples/{sample_id}/labels` | 保存/更新标注（同步） | body: `labels[]`（类别+框坐标） |
| GET | `/api/v1/annotation-tasks/{task_id}` | 标注任务整体状态（进度/当前样本） | 轮询（Job 结构） |
| POST | `/api/v1/features/extract` | 执行特征提取（**同步**）：时序/视觉/声音特征 + 统一向量 | body: `weld_id`, `version_id`, `normalization`(Z-Score/Min-Max/L2/无), `format`(NPY/CSV/JSON/PT) |
| GET | `/api/v1/features/{extraction_id}` | 特征提取结果（导出时使用） | — 需登录 |

### 3.5 📦 datasets 数据集

| 方法 | 路径 | 功能 | 关键参数 / 请求体 |
|---|---|---|---|
| GET | `/api/v1/datasets` | 数据集列表（任务类型/样本数/完成度/版本/状态） | 需登录 |
| POST | `/api/v1/datasets` | 新建数据集 | body: `name`, `task`, 样本来源 |
| GET | `/api/v1/datasets/{dataset_id}` | 详情：样本统计 / 训练验证测试划分 / 数据质量 / 更新时间 | — 需登录 |
| GET | `/api/v1/datasets/{dataset_id}/dimensions` | 输入维度状态：`Voltage/GasSpeed/Current/Molten_feature/Sound_feature/焊缝照片/熔池视频`（已具备/缺失/必需） | — 需登录 |
| GET | `/api/v1/datasets/{dataset_id}/readiness` | 模型适配检查：按任务动态返回检查项与「可训练/暂不可训练」 | — 需登录 |
| GET | `/api/v1/datasets/{dataset_id}/versions` | 数据集版本列表 | 需登录 |
| POST | `/api/v1/datasets/{dataset_id}/versions` | 新建版本（固定快照，不覆盖旧版，保证可复现） | body: `name`, `note` |
| GET | `/api/v1/datasets/{dataset_id}/versions/{version_id}` | 版本详情（固定样本清单、划分） | — 需登录 |
| POST | `/api/v1/datasets/{dataset_id}/versions/{version_id}/build-tasks` | 数据集构建任务（**异步**：从切分样本/标注生成固定版本） | body: `source` |
| GET | `/api/v1/datasets/{dataset_id}/lineage` | 数据血缘：原始焊缝→标注任务→数据集版本→模型训练 | — 需登录 |

### 3.6 🤖 models 模型中心

| 方法 | 路径 | 功能 | 关键参数 / 请求体 |
|---|---|---|---|
| GET | `/api/v1/models` | 模型仓库列表 + 汇总（总数/生产候选/最近训练/GPU 资源） | 需登录 |
| GET | `/api/v1/models/{model_id}` | 模型详情 | — 需登录 |
| POST | `/api/v1/training-tasks` | 创建训练任务（**异步**） | body: `dataset_version_id`, `base_model_id`, `epochs`, `batch_size`, `learning_rate`, `val_ratio`, 高级参数 |
| GET | `/api/v1/training-tasks/{task_id}` | 训练状态：mAP@50/精确率/召回率 + 训练/验证损失曲线 + 进度 | 轮询（Job 结构） |
| GET | `/api/v1/training-tasks/{task_id}/logs` | 训练日志 | 需登录 |
| POST | `/api/v1/test-tasks` | 创建测试任务（**异步**） | body: `model_version_id`, `dataset_version_id`, `tasks[]`(异常分类/质量预测/推理延迟) |
| GET | `/api/v1/test-tasks/{task_id}` | 测试结果：准确率/召回率/F1/推理时延 + 混淆矩阵 | 轮询（Job 结构） |
| POST | `/api/v1/inference-tasks` | 提交推理（**异步**） | body: `model_version_id`, `input`(object_key/样本), `input_type`(图像/视频帧/时序) |
| GET | `/api/v1/inference-tasks/{task_id}` | 推理结果：预测框/类别/置信度/耗时 | 轮询（Job 结构） |

### 3.7 📁 files · ⚙️ jobs · 📄 reports（横切）

| 方法 | 路径 | 功能 | 关键参数 / 请求体 |
|---|---|---|---|
| POST | `/api/v1/files/upload` | 上传文件到 MinIO（**小文件 <100MB** 代理转发），返回 object_key + URL | multipart: `file` |
| POST | `/api/v1/files/presign-upload` | **大文件预签名直传**（≥100MB，登记原始文件 ≤2GB）：返回可 PUT 的 upload_url + object_key | body: `size`, `content_type`, `prefix` |
| GET | `/api/v1/files/{object_key}/url` | 预签名下载/播放 URL（支持 Range 拖动播放） | query: `expires` |
| GET | `/api/v1/jobs/{job_id}` | **通用任务状态轮询**（对齐/切分/训练/测试/数据集构建共用） | — 需登录 |
| POST | `/api/v1/reports/export` | 通用导出：核验报告/分析报告/标注集/特征集/测试报告 | body: `type`, `ref_ids[]`, `format` |

---

## 4. 前端接口层

### 4.1 目录结构（新建，不触碰现有 `App.tsx`）

```
src/api/
├── client.ts     # request() 封装：baseURL=/api/v1、注入 JWT、解包 code、统一错误提示
├── types.ts      # 全部实体类型（见 §2）
├── auth.ts       # 登录 / 当前用户
├── dashboard.ts  # 总览统计
├── welds.ts      # 焊缝数据、登记、版本、核验
├── analysis.ts   # 对齐/分析/切分/标注/特征
├── datasets.ts   # 数据集维护
├── models.ts     # 模型仓库/训练/测试/推理
├── files.ts      # 上传/预签名
├── jobs.ts       # 任务轮询
└── reports.ts    # 导出
```

### 4.2 函数签名（命名：`动词 + 资源`，camelCase，一律返回类型化 Promise）

```ts
// auth.ts
login(username: string, password: string): Promise<{ access_token: string; user: User }>
getMe(): Promise<User>

// dashboard.ts
getStats(): Promise<DashboardStats>
getAttributes(): Promise<DashboardAttributes>
getDistributions(): Promise<DashboardDistributions>
getProjects(): Promise<Project[]>

// welds.ts
listWelds(params: WeldListQuery): Promise<Page<DataRecord>>          // GET /welds
getWeld(weldId: string): Promise<DataRecord>                          // GET /welds/{weld_id}
createRegistration(body: RegistrationForm): Promise<Registration>     // POST /registrations
updateRegistration(id: string, body: Partial<RegistrationForm>): Promise<Registration>
getRegistration(id: string): Promise<Registration>                    // GET /registrations/{id}
listVersions(weldId: string): Promise<DataVersion[]>                  // GET /welds/{id}/versions
getVersion(weldId: string, versionId: string): Promise<DataVersion>   // GET /welds/{id}/versions/{version_id}
runValidation(weldId: string, versionId: string): Promise<ValidationReport>
getValidation(weldId: string, versionId: string): Promise<ValidationReport>

// analysis.ts
listCandidates(): Promise<DataRecord[]>
createAlignmentTask(weldId: string, versionId: string, modalities: string[]): Promise<{ job_id: string }>
getAlignmentTask(taskId: string): Promise<Job<AlignmentResult>>
getSignals(weldId: string, versionId: string, opts: SignalQuery): Promise<SignalData>
getAnalysisMode(weldId: string, versionId: string, mode: AnalysisMode, channel: string): Promise<AnalysisViewData>
getAnalysisResult(weldId: string, versionId: string): Promise<AnalysisResult>
createSplitTask(weldId: string, versionId: string, rules: SplitRules): Promise<{ job_id: string }>
getSplitTask(taskId: string): Promise<Job<SplitResult>>
listLabelCategories(): Promise<LabelCategory[]>
listAnnotationSamples(taskId: string, page: number): Promise<Page<Sample>>
getAnnotationSample(taskId: string, sampleId: string): Promise<Sample>
aiPretag(taskId: string, sampleId: string): Promise<Annotation[]>
saveAnnotation(taskId: string, sampleId: string, labels: Annotation[]): Promise<void>
extractFeatures(body: FeatureExtractRequest): Promise<FeatureExtraction>
getFeatureExtraction(id: string): Promise<FeatureExtraction>

// datasets.ts
listDatasets(): Promise<Dataset[]>
createDataset(body: { name: string; task: string }): Promise<Dataset>
getDataset(id: string): Promise<Dataset>
getDimensions(id: string): Promise<DimensionStatus[]>
getReadiness(id: string): Promise<ReadinessCheck>
listDatasetVersions(id: string): Promise<DatasetVersion[]>
createDatasetVersion(id: string, body: { name: string; note?: string }): Promise<DatasetVersion>
getDatasetVersion(id: string, versionId: string): Promise<DatasetVersion>
getLineage(id: string): Promise<LineageNode[]>
createBuildTask(id: string, versionId: string): Promise<{ job_id: string }>

// models.ts
listModels(): Promise<{ summary: ModelSummary; models: Model[] }>
getModel(id: string): Promise<Model>
createTrainingTask(body: TrainingConfig): Promise<{ job_id: string }>
getTrainingTask(id: string): Promise<Job<TrainingResult>>
getTrainingLogs(id: string): Promise<string>
createTestTask(body: TestConfig): Promise<{ job_id: string }>
getTestTask(id: string): Promise<Job<TestResult>>
createInferenceTask(body: InferenceRequest): Promise<{ job_id: string }>
getInferenceTask(id: string): Promise<Job<InferenceResult>>

// files.ts
uploadFile(file: File, onProgress?: (p: number) => void): Promise<{ object_key: string; url: string }>   // 小文件 <100MB
presignUpload(req: { size: number; content_type: string; prefix: string }): Promise<{ object_key: string; upload_url: string }>
getFileUrl(objectKey: string, expires?: number): Promise<{ url: string }>

// jobs.ts
getJob(jobId: string): Promise<Job<unknown>>

// reports.ts
exportReport(body: ExportRequest): Promise<{ url: string }>
```

### 4.3 横切工具
- `useJob(jobId)`：轮询 `jobs.getJob()`，直到 `succeeded` / `failed`（重算任务共用）。
- token 存 `localStorage`，`client.ts` 自动注入 `Authorization`；`code !== 0` 时统一提示。

---

## 5. 功能覆盖对照表

| 页面 / 功能 | 前端调用 | 后端接口 |
|---|---|---|
| 登录 / 侧边栏用户卡 | `auth.login()` `auth.getMe()` | `POST /auth/login` `GET /auth/me` |
| 总览 · 四个统计卡 | `dashboard.getStats()` | `GET /dashboard/stats` |
| 总览 · 属性面板（焊机/缺陷/多模态/频率） | `dashboard.getAttributes()` | `GET /dashboard/attributes` |
| 总览 · 占比分布/词云 | `dashboard.getDistributions()` | `GET /dashboard/distributions` |
| 总览 · 数据项目卡片 | `dashboard.getProjects()` | `GET /dashboard/projects` |
| 数据列表 · 筛选/分页/去重 | `welds.listWelds(params)` | `GET /welds` |
| 数据列表 · 选中数据上下文 | `welds.getWeld(id)` | `GET /welds/{weld_id}` |
| 数据登记 · 新建/编辑 | `welds.createRegistration()` `updateRegistration()` | `POST` / `PATCH /registrations` |
| 数据登记 · 原始文件上传 | `files.uploadFile()` | `POST /files/upload` |
| 数据登记 · 最近登记列表 | `welds.listWelds(tab=最近)` | `GET /welds` |
| 数据核验 · 执行 | `welds.runValidation()` | `POST …/validation` |
| 数据核验 · 15 规则明细 | `welds.getValidation()` | `GET …/validation` |
| 数据版本 · 版本链 | `welds.listVersions()` | `GET /welds/{weld_id}/versions` |
| 分析 · 选择数据 | `analysis.listCandidates()` | `GET /analysis/candidates` |
| 对齐 · 时间轴/事件/轨道 | `analysis.createAlignmentTask()` + `useJob(getAlignmentTask)` | `POST` / `GET …/alignment-tasks` |
| 切分 · 规则/预览/样本数 | `analysis.createSplitTask()` + `useJob(getSplitTask)` | `POST` / `GET …/split-tasks` |
| 信号分析 · 时域波形+滤波 | `analysis.getSignals()` | `GET …/signals` |
| 信号分析 · PSD/STFT/DWT/小波/相图/PDD | `analysis.getAnalysisMode(mode)` | `GET …/analysis/{mode}` |
| 信号分析 · 异常区段/稳定度 | `analysis.getAnalysisResult()` | `GET …/analysis/result` |
| 标注 · 标签类别 | `analysis.listLabelCategories()` | `GET /label-categories` |
| 标注 · 样本列表/详情 | `analysis.listAnnotationSamples()` `getAnnotationSample()` | `GET …/samples(/{id})` |
| 标注 · AI 预标注 | `analysis.aiPretag()` | `POST …/ai-pretag` |
| 标注 · 保存/更新 | `analysis.saveAnnotation()` | `POST …/labels` |
| 特征提取 · 三类模态特征+统一向量 | `analysis.extractFeatures()` | `POST /features/extract` |
| 特征提取 · 导出 | `analysis.getFeatureExtraction()` | `GET /features/{id}` |
| 数据集 · 列表/新建/详情 | `datasets.listDatasets()` `createDataset()` `getDataset()` | `GET` / `POST /datasets` |
| 数据集 · 输入维度/适配检查 | `datasets.getDimensions()` `getReadiness()` | `GET …/dimensions` `…/readiness` |
| 数据集 · 版本/血缘/构建 | `datasets.listDatasetVersions()` `getLineage()` `createBuildTask()` | `/versions` `…/lineage` `…/build-tasks` |
| 模型仓库 · 列表/汇总/详情 | `models.listModels()` `getModel()` | `GET /models(/{id})` |
| 训练 · 配置/开始/指标曲线/日志 | `models.createTrainingTask()` `getTrainingTask()` `getTrainingLogs()` | `POST` / `GET /training-tasks` |
| 测试 · 配置/指标/混淆矩阵 | `models.createTestTask()` `getTestTask()` | `POST` / `GET /test-tasks` |
| 推理 · 提交/结果 | `models.createInferenceTask()` `getInferenceTask()` | `POST` / `GET /inference-tasks` |
| 播放/下载（视频/图片/报告） | `files.getFileUrl()` | `GET /files/{object_key}/url` |
| 任务轮询（通用） | `jobs.getJob()`（经 `useJob`） | `GET /jobs/{id}` |
| 导出报告/结果（各工具栏） | `reports.exportReport()` | `POST /reports/export` |

> **覆盖说明**：页面上的"刷新"按钮 = 重新调用对应列表/详情接口，无独立端点；"更换数据集"= 重新调用 `GET /datasets`。

---

## 6. 附录

### 6.1 任务状态机（Job）

```
pending ──► running ──► succeeded
              │
              └──────► failed（result 为空，error 记录原因）
```

- `progress`：0~100，running 期间更新；succeeded 时 `result` 携带业务结果。

### 6.2 同步 / 异步划分

| 方式 | 接口 |
|---|---|
| 同步 | 登录、总览统计、列表/详情查询、登记增改、核验、信号分析、特征提取、AI 预标注、标注保存、上传、导出、通用轮询 |
| 异步（Job） | 多模态对齐、数据切分、数据集构建、模型训练、模型测试、推理 |

### 6.3 预留项（本期不实现，文档中占位）

- **系统设置**：侧边栏入口暂无对应页面 → 预留 `GET/PUT /settings`。
- **角色权限**：本期仅登录，预留 `GET /users`、`POST /users`、角色字段。
- **版本回滚**：README 提到"版本回滚接口"，本期只读版本链，预留 `POST …/versions/{version_id}/rollback`。
- **审计日志**：登记页提到"所有操作写入审计日志"，预留 `GET /audit-logs`。
