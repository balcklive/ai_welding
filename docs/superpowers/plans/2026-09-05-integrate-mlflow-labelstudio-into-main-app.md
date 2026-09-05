# 集成 MLflow 与 Label Studio 到主应用：一期打通标注与训练全链路（长期实施计划）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. 本计划为**里程碑级路线**；每个里程碑/工作轨开工前，按 writing-plans 单独展开成细粒度任务清单。
>
> **Goal（一期，2026-09-05 定案）：** 把主应用业务闭环里的「标注」与「训练」两条链路**真正由 Label Studio 与 MLflow 承接并贯通**——
> - **标注**：平台建标注任务（仍先选焊缝）→ 样本推 LS 对应项目（目标检测 / 熔池分割 / 时序分段）→ 标注员在 **LS** 完成 → 回写 `annotations`（业务库权威）→ 数据集构建/训练链路沿用。
> - **训练**：训练任务 → 真实 CPU Torch 内核 → **MLflow Server** 记 Run（params/metrics/数据集快照摘要 artifact）+ 注册模型 → 回填 `model_versions`/`job.result` → 平台模型/实验视图消费。
>
> 业务库（`annotations`/`dataset_items`/训练 Job/`model_versions`）始终为权威；LS/MLflow 是**捕获/执行/展示层**。一期交付一个**端到端可在 UI 验收的用户流**；二期（数据集管理 P0 / 能力吸收）后续单开。
>
> **Architecture:** 一切经公开 API/SDK + 薄适配层（`backend/app/integrations/`，best-effort 仿 `mlflow.py`）；LS 经官方 `label-studio-sdk`（PAT 设一次即可）+ MinIO 预签名**长 TTL**媒体；MLflow 已是 compose 内 `server` 模式，app 走 `http://mlflow:5000`。数据/元数据不双写、不复制 LS/MLflow 的 schema。
>
> **上游：** spec `docs/superpowers/specs/2026-09-05-mlflow-dataset-annotation-design.md` §3/§4；进展 `docs/机器学习平台集成进展与方向.md`；已完成 `superpowers/plans/2026-09-05-mirror-third-party-images.md`、`2026-09-05-compose-deploy.md`。原计划按 M1/M2/M3/M4 编号；2026-09-05 评审后改为 **一期 = 原 M1（LS 标注，含前端）+ 原 M2（MLflow 训练）**，**二期 = 原 M3**，**长期 = 原 M4**。

## 已确认决策（2026-09-05 评审定案，本计划据此修订）

1. **M1 含最小前端录入切换（P1 并行）**：平台"数据标注"页的新标注任务经 UI 路由到 LS（优先 embed iframe，LS 无 CSP 白名单限制；否则新标签页 + 回平台刷新）；平台保留样本列表/标注**只读**展示与掩膜/segment 导出。自研画布（Annotorious/ECharts）录入路径暂不删，`off` 模式回退旧路径；**P2 下线另立计划**。
2. **`annotation_task` 完成语义 = 一等公民的「LS 等待」态**：与 Job 快速终态解耦；executor **不抢占**等待态任务；数据集构建/训练 readiness 闸门 =「标注已实际回写」而非 job 终态；终态由 webhook/轮询对账驱动，幂等。
3. **媒体访问 = MinIO 预签名长 TTL**（覆盖标注会话周期，按天/周）+ 适配层**对账刷新**已过期 task data；不经 `/api` 代理；保持"LS 不复制媒体本体"（个别媒体若 LS 实测回源不稳，再评估 copy_data 本地缓存，MinIO 仍权威）。
4. **标签类别补回第 6 类「熔池」**：`label_categories` seed/迁移补 6 类（与文档口径一致，消除"文档 6 类/代码 5 类"漂移）；LS 项目标签 schema 与平台类别**按标注语义校准**（见轨道 A）。

## Global Constraints

- 业务库权威；外部服务只做捕获/执行/展示层，不引入其 schema、不双写。
- 适配层 best-effort：LS/MLflow 不可达 → 仅告警/不炸业务 Job（铁律，同 `integrations/mlflow.py`）。
- **「LS 等待」任务不被 executor 抢占**；终态由回写/对账驱动；executor 失败兜底不得把等待态误标 succeeded。
- 媒体访问用 MinIO 预签名 URL（TTL 覆盖标注会话，过期对账刷新）；不经 `/api` 代理；量大后改 S3/MinIO connector；LS 默认不复制媒体本体。
- 敏感配置（LS URL/API key、MLflow 若开 auth 的账号密码）只进服务器 `.env`，不进仓库。
- 镜像版本 pin 不动（LS `1.23.0`、MLflow digest `e72e…`）；改版走 mirror workflow。
- 改接口/表/对象键同步三份契约 + 涉及目录 CLAUDE.md；LS/MLflow 后端暂 SQLite 落卷，规模上来再评估。
- **标签类别权威口径 = 平台 6 类（含熔池）**；LS 各项目标签 schema 为映射目标，不一致时按标注语义校准（必要时经 LS API 改项目模板并回写映射）。
- **同宿主服务走内网、浏览器走公网（双端点，2026-09-05 已实测定案·只改 MinIO）**：app/LS/mlflow/MinIO 同机（MinIO/MySQL 为**同机宿主进程**非容器，`182.61.59.135` 上 8290/8206 是云边缘→本机 9000/3306 的端口映射）。服务端数据面绕公网 hairpin 吃 ~5-6Mbps 公网入口瓶颈（见 memory `deploy-server-upload-bandwidth`）。**落点（代码已落地）**：后端 `_client`（数据面）走内网 `MINIO_SERVER_ENDPOINT`（= `172.18.0.1:9000` docker 网关，容器直连已验证 1ms；空则回退 `MINIO_ENDPOINT`）；预签名 `_sign_client` 恒走公网 `MINIO_ENDPOINT`（182.61.59.135:8290，交到浏览器的 URL）；compose mlflow `MLFLOW_S3_ENDPOINT_URL=http://${MINIO_SERVER_ENDPOINT:-${MINIO_ENDPOINT}}`（嵌套默认已实测可用）。LS 媒体接入时按"LS 服务端拉取走内网、浏览器直开走公网"分。**MySQL 仅绑 `127.0.0.1`，容器不可直连 → 本期不改**（小查询非带宽瓶颈）。**生效仍需服务器 `.env` 设 `MINIO_SERVER_ENDPOINT=172.18.0.1:9000` 后重部署/重起 compose**（见 Execution Handoff）。

---

## 前置已完成（原 M0）

- [x] compose 多服务（LS@8224 / MLflow@8225 / app 蓝绿挂 `aiwelding-net`）；`app` 切 `MLFLOW_MODE=server` + `MLFLOW_TRACKING_URI=http://mlflow:5000`。
- [x] 镜像 mirror workflow + 服务器验证（LS ACR pull + smoke；MLflow GHCR 直拉 + smoke）。
- [x] LS 标注模板项目 3/4/5 建好（3=目标检测 RectangleLabels 4 缺陷类 / 4=熔池分割 BrushLabels 单类 / 5=时序 TimeSeries 4 类）。验收/测试记录见进展文档。

---

## 一期·轨道 A：LS 标注集成（原 M1，含前端；代码优先）

**目标**：主应用「标注」链路走 LS——标注员在 LS 完成、结果回写 `annotations`、数据集构建/训练沿用；平台新标注任务经 UI 路由 LS（决策 1）。

**Files**（建议）：
- Create: `backend/app/integrations/labelstudio.py`（client 初始化 + 项目映射 + 建 task + 拉标注→转换 + 幂等回写 + 预签名 TTL 刷新）
- Create: `backend/app/models/` LS task↔platform sample 映射表（建议新表 `annotation_ls_sync`：`annotation_task_id`/`sample_id`/`ls_project_id`/`ls_task_id`/`ls_annotation_id?`/回写状态/幂等键；契约回写 `docs/数据库设计.md`）
- Create: `backend/app/services/annotation_ls.py`（「LS 等待」状态联动 + webhook 处理 + 对账/刷新；原 `annotation.py` 保留 `off` 路径与只读复用）
- Create: `backend/app/api/v1/labelstudio.py`（`POST /api/v1/labelstudio/webhook` 共享 secret 校验 + 手动触发/状态查询，鉴权）+ `router.py` 追加 include
- Modify: `backend/app/core/config.py`（`LABEL_STUDIO_MODE=off|on`、`LABEL_STUDIO_INTERNAL_URL`、`LABEL_STUDIO_PUBLIC_URL`、`LABEL_STUDIO_WEBHOOK_BASE`、`LABEL_STUDIO_API_KEY`、项目映射）+ `.env.example`
- Modify: `label_categories` 补「熔池」第 6 类（seed + 新迁移，编号以实际 head 为准）+ 契约回写 + `docs/CLAUDE.md` 漂移清理（决策 4）
- Create: 前端最小录入切换——`src/features/annotation/AnnotationWorkspace.tsx`（新任务→LS 跳转/embed + 回平台刷新；只读结果展示来自回写 `annotations`；off 模式保留旧画布）、`src/api/analysis.ts`/`types.ts`（LS 跳转/回写状态查询）、新 LS 嵌入/跳转组件
- Test: `backend/tests/test_labelstudio_integration.py`（LS 不可达/off 不炸；webhook secret 鉴权；映射转换单测；幂等重复回写；executor 不抢占等待态）
- 依赖：`uv add label-studio-sdk`；MinIO presign 长 TTL 能力

**关键步骤/验收**：
- [ ] SDK 客户端：`LabelStudio(base_url=LABEL_STUDIO_INTERNAL_URL, api_key=...)`；模式 `off` 时全链路跳过（best-effort）。**URL 三套**：app→LS API 走 `http://label-studio:8080`（内网）；LS→app webhook 走 `http://ai-welding:8000/api/v1/labelstudio/webhook`（蓝绿稳态容器名 `ai-welding` 稳定，deploy 窗口短时中断可重试）；标注员/嵌入页 UI 链接走 `LABEL_STUDIO_PUBLIC_URL`（公网宿主端口）。
- [ ] 项目映射**按标注语义**（非当前 source 字符串）：图像/关键帧**目标检测**（4 缺陷类）→ 项目 3；**熔池分割/视频帧多边形**（第 6 类熔池）→ 项目 4；**时序分段**（4 缺陷类）→ 项目 5。校准点：检测项目缺「正常」类（定"未标注即正常"或给项目 3 补标签二选一）；视频帧"熔池"硬编码默认标签改从 `label_categories` 取（决策 4）。映射与 LS 模板最终标签集回写。
- [ ] 建任务：`client.tasks.create(project, data={image|csv|ts: 预签名长 TTL URL + 内置 sample_id})`；写 `annotation_ls_sync`；`annotation_task` 置「LS 等待」态（**executor 不抢占**，不跑 simulate_annotation）。
- [ ] **时序任务媒体 = 专用导出 CSV**（选列：核心 4 或 +weld_speed，降采样，显式 `time` 列），LS TimeSeries 时间轴单位与平台"秒"换算固定；**任务↔signal_ingest 绑定**在创建时记录（`ingest_id`/`object_key`/通道集）。新时序格式 `schema_version=2` 动态 16 列（commit `6fc6697`）下整 CSV 直推会让 LS 标注面板塞满近常值的六轴/熔池列。
- [ ] LS UI 标注（平台 embed iframe / 新标签页）→ 平台只读样本/标注（来自回写 `annotations`）。
- [ ] 拉回（决策 2）：webhook `annotation_created/updated` → 校验 secret → 拉该 LS task 标注 → region JSON 映射 `Annotation` 行（rectangle→box / brush|polygon→polygon+轮廓 / timeseries range→segment `start_time|end_time`）→ `annotation_task` 完成 + job 回填 → 数据集构建沿用。**多标注/审核策略**：取"最后提交/已审核"、跳 draft/cancelled/empty；`annotator` 存 LS 用户名（同名账号约定）。**幂等**：重复事件/重复对账不重复落行。
- [ ] 轮询兜底：`tasks.list` 定期对账（幂等，避免丢 webhook）+ **刷新已过期预签名 URL**（决策 3）。
- [ ] 验收（轨道 A）：UI 建一个标注任务 → LS 对应项目出现 task 且标注页可达（embed/新标签）；LS 内完成标注 → 平台只读可见回写 `annotations`、行数与 LS 有效标注一致；等待态不被 executor 抢跑、数据集构建在未回写前不可用；LS `off`/不可达下建任务不炸、走原模拟/旧路径。

---

## 一期·轨道 B：MLflow 训练链路落地（原 M2，含 DM-02 快照摘要）

**目标**：主应用「训练」链路以 MLflow Server 为记录/注册执行层——真实训练 → Run（params/metrics/快照摘要 artifact）→ register_model → 回填 `model_versions`；平台实验/模型体验读 Run。真实算法内核本体（焊接 SOTA）属算法专家另立任务，本期只接入**封装与记录链**。

- [ ] 训练记录/注册链：handler（`services/models.py::run_training`）成功时经 `mlflow.<flavor>` 挂 `log_model`（真实 `torch_training.run` 的 state_dict/特征）+ `register_model`；`run_id`/注册模型名版本写 `job.result` 并回填 `model_versions`（新增 `model_versions.mlflow_run_id`（+注册模型版本）列，一次迁移，编号以 head 为准；契约回写 `docs/数据库设计.md`）。真实内核边界不变：换内核只动 `torch_training.py`、保持 `CpuTrainingResult` 契约。
- [ ] **训练特征口径按新时序格式校准（前置，别默认已可消费）**：commit `6fc6697` 后真实 CSV 为动态 16 列（`schema_version=2`），而 `torch_training._csv_values`（`services/torch_training.py:127`）把整 CSV 全数值压平后取 8 统计量——4 列模拟样本与 16 列真样本混入同一数据集时特征语义漂移（近常值六轴/熔池 px 淹没核心信号）。先把特征抽取固定到核心通道集或逐通道统计，再接真数据训练。
- [ ] 快照摘要进 Run（DM-02，自二期并入，与 M3 解耦）：`run_training` 成功后读 `DatasetVersion` 的 `version_no/split/quality/item_count/snapshot_id`，以 params 记关键项；以 JSON artifact 记完整 `dataset_snapshot.json`；同摘要并入 `job.result`。→ 训练 Run 自带"用了哪份不可变数据"的自证。
- [ ] 平台展示（先读后嵌入，**避免双源**）：训练详情/模型版本继续以 DB 权威渲染；新增「实验/对比」只读视图经 MLflowClient 读 Run 的 params/metrics/artifacts（loss_curve/confusion_matrix/dataset_snapshot），UI 嵌入 MLflow 或平台自绘（先自绘只读，借思想）。
- [ ] MLflow 若需多人/外网：开 basic-auth（compose `--app-name basic-auth` + `basic_auth.ini` + secret）或反代；app 加 `MLFLOW_TRACKING_USERNAME/PASSWORD`（**本期可选**，当前内网无鉴权可后置）。
- [ ] 验收（轨道 B）：训练 Job succeeded → MLflow Server 出现 FINISHED Run（params/metrics/loss_curve/dataset_snapshot artifact）+ Registered Model；`model_versions` 回填 run_id/注册版本；平台实验对比视图可读；MLflow `off`/不可达时训练 Job 不炸（回退仅 DB 记录）。

---

## 一期总验收（轨道 A + B 贯通）

端到端用户流（UI 可操作）：**登记 → 核验 → 切分样本 → 建标注任务 → LS 标（检测/熔池分割/时序）→ 回写 `annotations` → 数据集构建（闸门=已回写）→ 训练（MLflow Run + 注册模型）→ `model_versions` → 平台只读看标注结果与实验/模型版本**。任意外部服务下线：对应环节仅告警、业务 Job 与业务库数据不损坏、回退路径可用（LS `off` → 旧模拟/画布路径；MLflow `off` → 仅 DB 记录）。

---

## 二期·M3：数据集管理 P0（backlog，触发后单开）

- DM-01：数据集概览渲染标签分布面板（`label_distribution` 已返回；回写 `annotations` 后消费更完整）。
- DM-03：构建质量扩展（split 内类别分布 + 不平衡度）+ 划分类别平衡（分层划分）；回写 `docs/数据库设计.md` §3.15。
- ~~DM-02~~：训练记数据集快照摘要进 MLflow Run —— **已并入一期轨道 B**，从 M3 移除。

## 长期·M4：能力吸收与 UI 收敛（长期终点；触发后单开计划）

**触发**：主应用内标注/实验成为多人常态工作流、或外部服务运维成本显性后。
- [ ] 标注：平台内置标注画布（复用 `annotations` 数据模型与 LS 集成期沉淀的编辑体验，补齐多人/审核 QA），LS 转为可选后端引擎或停用。
- [ ] 实验/模型：平台内置 run 列表/指标对比/模型注册 UI；MLflow 保留为引擎（embedded 或 server）不再需要跳 UI。
- [ ] 外部服务降级可选：`docker compose` 中 LS/MLflow 可停用（数据卷保留迁移）。
- [ ] 全程业务库权威不变；契约束同步。

## 安全收敛（贯穿，尽早做）

- [ ] 云安全组把 8224/8225 收紧为办公室/内网 IP 白名单，或宿主改绑 `127.0.0.1`（app 走 compose 内网不受影响）；LS webhook 端点用**共享 secret 校验**，不依赖来源 IP。
- [ ] LS 建**专用集成账号** + Legacy Token（无则 PAT），key 进服务器 `.env`；轮换/吊销已暴露 PAT；LS 首个注册用户即 admin，标注员账号由管理员在 LS 内创建（同名账号约定映射回平台用户）。MLflow 若要多人访问再开 basic-auth。

## 待核实前提（写细粒度计划前先验，不阻塞里程碑拆分）

- [ ] **iframe embed**：LS 标注页响应是否带 `X-Frame-Options`/CSP `frame-ancestors`，决定平台"嵌入 vs 新标签页"（决策 1 hedge 的落点）。
- [ ] **预签名 TTL 上限**：MinIO/S3 预签名默认上限 7 天；确认存储层 `presign_get` 支持 >1 天 expires（`/files/url` 路由封顶 1 天 ≠ 存储层能力），与"长 TTL + 对账刷新"一致。
- [x] **网络端点拓扑（已核实，2026-09-05）**：SSH 核实 MinIO/MySQL = 同机宿主进程（非容器）。MinIO 绑 `*:9000`，容器经 `172.18.0.1:9000` / `192.168.31.79:9000` 直连可达（HTTP 200 / 1ms）；MySQL 仅绑 `127.0.0.1:3306`，容器不可直连 → 双端点只内网化 MinIO（代码已落地），MySQL 不动。
- [ ] **历史数据回填**：加「LS 等待」状态列时存量 annotation_tasks 的默认值/回填 + 蓝绿 expand/contract 兼容。
- [ ] **LS 等待态前端表达**：等待期前端不做进度 spinner，改"去 LS 标注"链接 + 刷新按钮/轮询（随决策 1 UI 切片定义）。
- [ ] **LS 项目4 工具**：平台视频帧是多边形顶点（`kind=polygon`），LS id4 现为 BrushLabels——定"LS 改 PolygonLabels 模板"还是"接受掩膜回写→轮廓/rle 存储"（影响 `annotations` 存储与导出）。
- [ ] **熔池/正常标签的训练消费**：熔池入 `label_categories` 后与训练二分类折叠（`load_real_examples` 按"正常→正常、其余→缺陷"）的关系待定——熔池是分割对象非缺陷，需明确熔池是否参与训练折叠或仅语义分割专用（产品裁决）。

## Execution Handoff

- **一期轨道 A（M1）先动**（唯一带代码细节的轨）：按 writing-plans 展开细粒度清单 → 分任务实现 + 测试 + 提交；随后**轨道 B（M2）**；最后跑**一期总验收**。
- 前置依赖：轨道 A 需 M0 已起的 LS 服务 + `label_categories` 第 6 类迁移先落；轨道 B 需 M0 已切的 MLflow server（已是 `MLFLOW_MODE=server`）。
- 二期 M3 仅剩 DM-01/DM-03（DM-02 已并入轨道 B）；M3/M4 触发后单开计划。
- 每推 main 仅重部署 app；LS/MLflow 镜像 pin 不变即不重部署。
