# 机器学习未来规划推进方案（MLflow 收尾 / 数据集管理执行 / 标注平台采用 Label Studio）

> 日期：2026-09-05
> 性质：**决策 + 路线文档（本轮不写码）**。文档把"模型训练 = MLflow、数据标注 = Label Studio、数据集管理 = 参考 FiftyOne/Datumaro/lakeFS"这条未来规划落到可执行清单与架构决策，供评审后进入实施计划。
> 上游依据：`docs/模型中心开源集成评估.md`（MLflow 阶段与边界）、`docs/superpowers/plans/2026-08-29-dataset-management-reference-tasks.md`（DM-01~11，未执行）。
>
> **已定决策（2026-09-05）**：
> 1. **标注平台采用 Label Studio**，现有自研内嵌标注**全面切换**到 LS（业务编排与数据模型仍以本项目库为权威）。
> 2. **部署约束放开**：不再强制单容器；采用 **Docker Compose 多容器部署**，并要求 **GitHub Workflow 自动部署**跑通。
> 3. **MLflow 独立 Tracking Server 现在并入 Compose 常驻**（不再默认 embedded）。

## 1. 现状核对（以代码 / CLAUDE.md / 两份规划文档为准）

| 方向 | 规划 | 项目内现状 | 真实差距 |
|---|---|---|---|
| 模型训练 | MLflow | **第一阶段已落地**：`backend/app/integrations/mlflow.py`（embedded/server/off 三模式，默认 embedded = SQLite + MinIO artifact）；真实 CPU Torch 训练内核 `services/torch_training.py`（读固定数据集快照真实样本→8 维特征→正常/缺陷二分类→真 state_dict 写 MinIO `models/{id}/weights.pt`）；训练/测试/推理均记 Run | 差 **Phase 2**：真实焊接算法内核 + `log_model`/`register_model`；并随定案改默认 `server` 模式 |
| 数据集管理 | 借 FiftyOne/Datumaro/lakeFS 思想 | 决策已定：**借思想·不引依赖**（DM 计划 §零 四条硬约束）；DM-01~11 已定级成文 | 11 项全部未执行，是现成 backlog |
| 数据标注 | Label Studio | 自研标注**已成熟**：`services/annotation.py` Task 14 + kind（box/segment/polygon）+ 视频帧锚点 + 掩膜导出 + 6 类标签；前端 `react-image-annotate`/Annotorious 画布；数据管道真实，仅 AI 预标注为确定性模拟 | 已决策：**全面切换 LS**，见 §3 |

## 2. 批次 1：不依赖标注平台实现，可评审的落地清单

批次 1 是既有文档已认可的低风险执行项（MLflow 收尾 + 数据集管理 P0），与 LS 集成解耦，可先行评审/排期。

### 2.1 MLflow Phase 2 准备（与 DM-02 合并）

现 `record_training`（`services/models.py:239-243`）只记 `dataset_version_id` 一个 param，缺少"该 Run 用了哪个不可变快照、质量如何"的自证。批内一次做完：

1. **快照摘要进 Run（= DM-02）**：`run_training` 成功后读 `DatasetVersion` 的 `version_no/split/quality/item_count/snapshot_id`，以 params 记 `dataset_version_no`、`split_train/val/test`、`quality_repeat_rate` 等关键项；以 JSON artifact 记完整 `dataset_snapshot.json`；同摘要并入 `job.result`。涉及 `services/models.py::run_training` + `integrations/mlflow.py`（扩参或新增 `record_dataset_snapshot`，保持 best-effort 不抛异常铁律）。
2. **可追溯字段**：`model_versions`/`job.result` 增记 `mlflow_run_id`（与注册模型名/版本）；若落 `model_versions` 列需一次小迁移，契约回写 `docs/数据库设计.md`。
3. **真训练内核接入边界（仅约定，不实现算法）**：换内核只动 `torch_training.py` 内部，保持 `CpuTrainingResult` 契约；在 handler 挂 `mlflow.<flavor>.log_model` 与 `register_model`，`run_id`/注册模型写回 Job.result。业务表 `model_versions.status` 仍是权威。

### 2.2 DM-03：构建质量扩展 + 划分类别平衡（Datumaro 借思想）

- `_compute_quality`（`services/datasets.py:1053`）只有三比率 → 扩展按 split 统计各类别样本数 + 类别不平衡度（保留原三率，前端已消费勿改名）。
- `_assign_splits`（`services/datasets.py:1026`）按焊缝分组 seed=42 随机 8:1:1、只防泄漏不保平衡 → 升级为约束下平衡划分（保持 8:1:1 总量 + 各 split 类别比例接近全量；组数 <3 退化保留）。
- 影响：`dataset_versions.quality` JSON 扩展 → 回写 `docs/数据库设计.md` §3.15。

### 2.3 DM-01：数据集概览渲染标签分布面板（FiftyOne 借思想）

- 后端详情已返回 `label_distribution`（`api/v1/datasets.py:120`），前端 `DatasetWorkspace.tsx` 未消费 → 加分布条/柱状面板；空态兜底。**契约零改动**，纯前端。

### 2.4 批次 1 契约/文档影响汇总

| 任务 | 契约影响 |
|---|---|
| MLflow 快照摘要 | 无接口/表改动（若加 `model_versions.mlflow_run_id` 列另评估迁移） |
| DM-03 | `dataset_versions.quality` JSON 扩展 → `数据库设计.md` §3.15 |
| DM-01 | 无 |

## 3. 标注平台：采用 Label Studio，全面切换（已定案）

### 3.1 决策与"全面切换"的边界语义

- **决策**：标注平台采用自托管 Label Studio；现有自研内嵌标注全面切换。
- **"全面切换"边界（工程语义）**：被移除的是**内嵌标注画布与录入入口**（`react-image-annotate`/Annotorious 相关编辑流程）；**业务编排与数据模型不动**——`annotation_tasks / samples / annotations / dataset_items` 及数据集快照仍以本项目 MySQL 为权威。实际人工标注在 LS 中完成，经适配层**回写** `annotations` 表。这样下游（标注分布/数据集质量/训练标签折叠）全部不断链。
- 若评审认为"连编排数据模型也要搬进 LS"才算全面切换，请指出——本文按"编排/数据模型留本项目、录入切 LS"设计，理由：LS 的 schema 不适合承载焊缝快照血缘与 8:1:1 划分，搬过去会重造一个平行业务库（成本高且无收益）。

### 3.2 开源格局核证（为何是 LS 而非更轻的替代，2025–2026 检索）

按本平台模态组合 **图像框/多边形 + 视频帧 + 1D 时序分段 + 多人 + 服务端 API** 筛选，无"又全又轻"的服务平替：LS 是服务形态里最轻且原生支持时序分段标注（TimeSeries）的平台；CVAT 更重（Redis 必带）且无时序；X-AnyLabeling 是单人桌面 AI 预标工具非多人平台；Annotix（2026, MIT）桌面无自托管 REST 且过新。→ 换图像类工具会丢时序能力、被迫保留自研时序标注，变成两套并行更重。**定案维持 LS。**

### 3.3 集成架构（建议）

```text
本项目 FastAPI/业务库(MySQL)            Label Studio(自托管, 独立DB)
────────────────────────────          ──────────────────────────
标注任务创建(annotation_tasks)   ──①──► project 映射 + task 创建
样本 → MinIO 对象               ──②──► task data 带 预签名URL
                                       标注员在 LS UI 精标(框/多边形/时序区间/视频帧)
标注完成态                       ◄──③── LS API/webhook 拉取 regions
                                    → 适配层映射回写 annotations 行(kind 映射)
                                    → annotation_tasks 标完成 → job 回填 → 数据集构建继续走现有链路
审核 QA(accept/reject) 在 LS 内完成 ──④── 审核结果/版本以 annotation 行或标注审核标记带回
```

- **① project/任务映射**：按"标注任务 + 标签类别集"建 LS project，JSON 标签 schema 对应 box/polygon/时序分段模板；一个 `annotation_task` → 一组 LS task（每个待标样本一条）。
- **② 媒体访问**：task data 放 MinIO **预签名 URL**（沿用 OSS 直连思路，不经 `/api` 代理），LS 不复制媒体本体。
- **③ 回写映射**：LS regions → `Annotation` 行：box↔rectangle、polygon↔polygon、segment↔TimeSeries 区间；补 `annotator/operator`；平台层校验 kind 合规后再落库（沿用现有 save_labels 覆盖写语义）。回写时机用 LS 标注完成 webhook 或轮询导出，断点续标需幂等（防重复回写）。
- **④ 审核/账号**：LS 自带标注员账号 + 审核流程；账号与平台用户的映射先按"同名账号"约定，SSO 不在本期。AI 预标注：现有确定性模拟预标可下线，LS 模型辅助预标（SAM 等）列为后续可选，本期不做。

### 3.4 前端/业务流程改造面

- 分析与标注相关页：原内嵌标注交互改为**跳转/嵌入 LS 标注页**（LS 无 iframe 白名单限制则优先 embed；否则新标签页 + 回平台刷新状态）。
- 保留在平台内的只读能力：样本列表、标注结果只读展示（来自 `annotations` 行）、掩膜/segment JSON 导出（复用 `export_annotations`，基于已回写的 annotations 行）。
- 时序**快速浏览/预览**仍可在平台内（signals 预览等），但**录入**走 LS。

### 3.5 工作量与风险（诚实标注）

- 工作量：**高**。含 LS 服务落地 + 适配层（建 project/task、媒体预签名、回写映射、幂等）+ 前端改造（跳转/嵌入/只读态）+ 现有 `react-image-annotate`/Annotorious 相关代码下线 + 全链路联调（标注完成 → 数据集构建 → 训练标签折叠）。
- 风险点：回写映射与 kind 兼容（LS 多边形/时序导出结构与现有 `annotations` 列需对齐）；断点续标与并发去重；LS 独立账号体系；媒体预签名过期时长需覆盖标注会话。
- 建议过渡分两段：**P1 并行**（LS 承接新标注任务，内嵌入口保留指向 LS，先不删旧数据路径）→ **P2 下线**（确认无回归后删除内嵌编辑代码与依赖）。最终状态即"全面切换"。

## 4. 部署拓扑：Docker Compose 多容器（已定案）

### 4.1 服务清单（草案）

| 服务 | 镜像来源 | 说明 |
|---|---|---|
| `app` | 自建，ACR | FastAPI 同时服务 `/api` 与前端静态（沿用现 Dockerfile 多阶段） |
| `label-studio` | ACR mirror 官方镜像（见下） | 独立 DB；承接人工标注 |
| `mlflow` | ACR mirror 官方镜像（见下） | **Tracking Server 常驻**；backend store 用 MySQL，artifact store 用 MinIO `mlflow-artifacts` 桶 |
| MySQL / MinIO | 外部已有基础设施（连接在 `.env`） | 业务库 `ai_welding`、LS 库、MLflow 库同实例不同库，或分实例，执行阶段定 |

**镜像来源（2026-09-05 实测）**：生产机 `182.61.59.135:8222`（wwwroot，Docker 29.1.3）上实测结论——
- `app`：本仓库多阶段构建，随发布 build+push 到 ACR（`aliyun_kaka/ai_welding`）。
- **MLflow `ghcr.io/mlflow/mlflow`：服务器可直接从 GHCR 拉取并部署**（实测 369MB/247s，smoke-run `/health`=OK）→ 不强制 mirror，可直拉 GHCR（每次升级约数分钟）。是否再 mirror 到 ACR 仅为统一运维的可选项。
- **Label Studio `heartexlabs/label-studio`（Docker Hub）：服务器直拉失败**（`connection reset`，换 Docker Hub IP 复现 2 次）→ **必须 mirror 到 ACR**。本机与服务器都无法访问 Docker Hub，mirror 需在**能访问 Docker Hub 且持 ACR 凭据**的环境执行——最合适是 **GitHub Actions runner**（`deploy-docker.yml` 已用 `ALIYUN_ACR_*` secrets 登录 ACR）：pull 官方镜像 → tag `crpi-…/aliyun_kaka/label-studio:<tag>` → push ACR → 服务器从 ACR 拉。
- 版本固定：LS/MLflow 上游镜像用 tag 固定，仅在升级时重新 mirror/拉取。

默认假设（评审可改）：
- MySQL/MinIO **维持外部已有实例**，Compose 只编排 app/label-studio/mlflow 三个服务；LS 与 MLflow 各在共享 MySQL 建独立 database（如 `label_studio`、`mlflow`），MinIO 加 `mlflow-artifacts` 桶（LS 媒体仍走 `aiwelding` 预签名）。
- MLflow 模式：部署环境 `MLFLOW_MODE=server` + `MLFLOW_TRACKING_URI=http://mlflow:5000`；本地开发仍可 `embedded`。`integrations/mlflow.py` 三模式已支持，业务代码零改动。
- `app` 仍私有化单容器形态内部化（多服务仅是部署单元拆分，不改变业务内聚）。

### 4.2 GitHub Workflow 自动部署改造

- 现有 `.github/workflows/deploy-docker.yml` 是**单容器** `docker pull` + `docker run`。改造目标：`main` 校验（lint/typecheck/build/pytest）通过后 → `build-and-push` 只负责构建并推送 `app` 镜像到 ACR → SSH 到服务器执行 `docker compose pull`（`app` 从 ACR；LS/MLflow 从 ACR mirror 或官方仓库，见 §4.1 镜像来源）+ `docker compose up -d`；健康检查沿用 readiness。
- **LS 的 ACR mirror 独立于 `app` 发布，且必须在 GitHub Actions runner 上执行**（runner 能访问 Docker Hub；服务器/本机均不行，见 §4.1）：做一个按需 job（`workflow_dispatch` 或随发布附带）`pull heartexlabs/label-studio:<tag> → tag → push ACR`，服务器 `docker compose pull` 从 ACR 取 LS；MLflow 可直拉 GHCR，无需 mirror。
- 交付物：`docker-compose.yml`（或 compose.yaml）+ 服务器 `.env` 扩展（含 LS/MLflow 连接与首登账号）+ workflow 改造/新增。
- 注意：这是**独立的基础设施实施任务**，与批次 1 编码解耦；需在部署文档与根 CLAUDE.md 同步修订"单容器"字样。

## 5. 边界与明确不做

1. 不引入 FiftyOne/Datumaro/lakeFS/Pachyderm 任一作为运行依赖。**说明**：部署放开多容器后，DM 计划 §零 原"单容器"一条理由不再成立，但**其余三条理由仍在**（数据源重复、MySQL 为真源、规模在服务范围内），故数据集管理"借思想·不引依赖"**维持不变**，除非另行决策。
2. 批次 1 不实现真实焊接算法内核（属算法专家决策，另立任务）。
3. LS 的 SSO、模型辅助预标（SAM 等）、大批量导入导出工具不在本期。
4. 不复制 MLflow 内部 Store/Server/Web UI，只走公开客户端与官方镜像。
5. 数据集模型不改目录式、不做完整 Git 语义（沿用 DM 计划 §三）。

## 6. 待评审与下一步

**待评审**：
- §3.1"全面切换"边界语义（编排/数据模型留本项目、录入切 LS）是否接受；
- §3.5 过渡分两段（P1 并行 → P2 下线）是否接受；
- §4.1 默认假设（MySQL/MinIO 外部、LS 与 MLflow 共享 MySQL 分库、MinIO 加 `mlflow-artifacts` 桶）。

**下一步**：
1. 评审通过后，拆为若干实施计划：批次 1（MLflow 快照摘要/可追溯字段 + DM-03 + DM-01）；LS 集成 P1（§3.3 架构 + §4.1 服务）；部署拓扑（§4.2 compose + workflow）；后续再排 LS P2 下线。
2. 契约影响项（quality JSON、可能的 `model_versions` 列、前端页面跳转、部署描述）在执行阶段同步回写 `API接口清单.md / 数据库设计.md / OSS存储设计.md`、根 CLAUDE.md 与涉及目录 CLAUDE.md。
