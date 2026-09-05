# Docker Compose 部署（LS + MLflow 辅助服务，保留 app 蓝绿）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Docker Compose 在私有化服务器编排 Label Studio + MLflow 两个辅助服务，与主应用共享网络，同时**不改动 app 现有的单容器蓝绿发布**，为标注/实验追踪跑真工具。

**Architecture:** app（FastAPI+前端）继续由 `deploy-docker.yml` 单容器蓝绿 `docker run`；本 compose 只编排 `label-studio` 与 `mlflow`，落在外部网络 `aiwelding-net`（app 容器 attach 同网后按服务名访问）。两服务持久化用命名卷；MLflow artifact 走既有 MinIO 前缀；LS/MLflow 后端均 SQLite 落卷（阶段子系统的轻量选择，长期能力吸收入主应用后可弃）。分两阶段：**A = 起服务并验证（app 不动，零生产风险）**；**B = app 切 MLflow server + 工作流同步 compose（动 app 发布，逐项验证）**。

**Tech Stack:** docker compose / GitHub Actions（appleboy/ssh-action, scp-action）/ Label Studio 1.23.0（ACR）/ MLflow 3.16.0（GHCR digest）/ MySQL+MinIO 既有

**版本 pin（实测）**：LS `crpi-v5j14rjtcacf9f23.cn-shanghai.personal.cr.aliyuncs.com/aliyun_kaka/label-studio:1.23.0`；MLflow `ghcr.io/mlflow/mlflow@sha256:e72e134e4fd38a229cfbce1b8a8c19c6b4e8928f1ceb5dc136c891855212e998`。

## Global Constraints

- 服务器部署目录 `<DEPLOY_PATH>` = `/home/wwwroot/code/ai_welding`，其 `.env` 与 compose 同目录；compose 自动读 `.env` 变量替换。
- 生产容器 `ai-welding`（Up @8223）测试/变更全程不可受影响；回滚保留当前单容器方案直至 B 段验证通过。
- `MINIO_ENDPOINT` 为裸 `host:port`（无 scheme）；MLflow boto 需 `http://` 前缀 → compose 内 `MLFLOW_S3_ENDPOINT_URL: "http://${MINIO_ENDPOINT}"`。
- LS 官方镜像无可靠 admin 自动创建 env；**首个网页注册用户自动成为管理员**。
- 镜像版本用上表 pin；改版走 mirror workflow / GHCR 直拉，再更新本 compose。
- 契约影响同步：改 `.env.example`/新增 `docker-compose.yml` 时，同步仓库根 CLAUDE.md（部署描述）与涉及目录 CLAUDE.md；服务器 `.env` 不提交。

---

### Task A1: 仓库侧 compose 文件与 env 示例

**Files:**
- Create: `docker-compose.yml`（仓库根；部署时同步到 `<DEPLOY_PATH>`）
- Modify: `.env.example`（追加 `LABEL_STUDIO_PORT`/`MLFLOW_PORT` 与 server 模式注释）

**Interfaces:**
- Produces: `docker-compose.yml`（含 `networks.aiwelding-net`、卷 `ls_data`/`mlflow_data`、服务 `label-studio`/`mlflow`）；B 段工作流与 app 网络 attach 依赖其中网络名 `aiwelding-net`。

- [ ] **Step 1**: 已创建 `docker-compose.yml`（见仓库，内容含 healthcheck，LS 首启建库 `start_period=120s`）。
- [ ] **Step 2**: 已追加 `.env.example` 键 `LABEL_STUDIO_PORT=8224`、`MLFLOW_PORT=8225` 及 server 模式注释。
- [ ] **Step 3**: 更新根 `CLAUDE.md` 部署描述（单容器→多服务编排 + compose 说明）与 `.env.example` 关联描述。
- [ ] **Step 4**: Commit `docker-compose.yml` + `.env.example` + CLAUDE.md。

### Task A2: 服务器起 LS + MLflow 并验证（app 不动）

**Files:**
- Server: `<DEPLOY_PATH>/docker-compose.yml`（scp 上传）；`<DEPLOY_PATH>/.env`（如需覆盖端口，默认 8224/8225 则可不改）

**Interfaces:**
- Produces: 外部网络 `aiwelding-net`；容器 `label-studio`（8224）、`mlflow`（8225）；B 段 app 复用该网络与 `mlflow:5000`。

- [x] **Step 1**: 上传 compose 到 `<DEPLOY_PATH>`（scp 已执行）。
- [x] **Step 2**: 前置——服务器 Docker 无 compose 插件 → **以 wwwroot 安装用户级插件** `~/.docker/cli-plugins/docker-compose`（v5.5.1，下载自 GitHub，无需 root）；`docker network create aiwelding-net` + `docker compose up -d` 成功，两容器起。
- [x] **Step 3**: 健康检查通过：`label-studio` healthy @8224（`/health`=`{"status":"UP"}`，首启建库约 100s）；`mlflow` healthy @8225（`/health`=OK）。`docker inspect` 两容器均 healthy。
- [ ] **Step 4**: LS 管理员（人工）：浏览器首次打开 `http://<公网IP>:8224` → Sign Up 首个账号自动为 admin；记入团队密码本（不在代码库）。尚未执行。
- [x] **Step 5**: 生产复核通过：`ai-welding` Up 6 天 healthy，未受影响。
- [x] **Step 6**: 已登记 plans/CLAUDE.md。

### Task A3（Phase B）: app 切 MLflow server + attach 网络

**Files:**
- Modify: server `<DEPLOY_PATH>/.env`（`MLFLOW_MODE=server`、`MLFLOW_TRACKING_URI=http://mlflow:5000`）
- 无 app 代码改动（`integrations/mlflow.py` 已支持 server 模式，配置即切）。

- [ ] **Step 1**: 备份并改 server `.env`：`sed -i` 设 `MLFLOW_MODE=server`、`MLFLOW_TRACKING_URI=http://mlflow:5000`（保留 `MLFLOW_ARTIFACT_ROOT` 一致）。
- [ ] **Step 2**: 手动触发一次 app 部署（或等下次 main push），验证 app 容器 attach 同网后能访问 `mlflow:5000`。
- [ ] **Step 3**: 回归：训练一次 → `mlflow` 服务内新增 run（`docker exec mlflow python -c "...list runs..."` 或 UI `http://127.0.0.1:8225`）；MLflow 写入失败不使业务 Job 失败（best-effort 铁律回归）。
- [ ] **Step 4**: 若失败回退：`sed -i` 还原 `MLFLOW_MODE=embedded` 并重部署 app（app 不动 LS/MLflow）。

### Task A4（Phase B）: deploy-docker.yml 自动同步 compose 与起辅助服务

**Files:**
- Modify: `.github/workflows/deploy-docker.yml`（deploy job：scp 上传 compose + 网络/compose up；app 各 `docker run` 增 `--network aiwelding-net`）

- [ ] **Step 1**: deploy job 增加一步（`appleboy/scp-action`）把 `docker-compose.yml` 上传到 `<DEPLOY_PATH>`。
- [ ] **Step 2**: SSH 脚本在拉取 app 前先：
  ```bash
  cd "$DEPLOY_PATH"
  docker network create aiwelding-net 2>/dev/null || true
  docker compose up -d    # 幂等：只拉取/启动/更新 label-studio、mlflow
  ```
- [ ] **Step 3**: 现有 app `docker run` 三处（候选、正式、rollback_previous 里 rollback 启动）追加 `--network aiwelding-net`。
- [ ] **Step 4**: 提交 + 手动触发一次发布，验证：LS/MLflow 恒在、app 蓝绿正常、训练 run 写入 server。
- [ ] **Step 5**: 契约/文档同步（根 CLAUDE.md 部署段、`.github/workflows/CLAUDE.md`）。

### Task A5: 回滚与清理预案

- [ ] 记录回滚：A3/A4 任一步失败 → 还原 server `.env` MLflow 为 embedded + 用上一镜像 tag 重放现有 app 蓝绿脚本；LS/MLflow 容器保留但 app 不再依赖（`docker compose stop` 可临时停）。
- [ ] 若整体放弃辅助服务：`docker compose down`（保卷）或 `docker compose down -v`（连数据一起清）。

## Self-Review

- Spec §4 覆盖：服务清单/镜像来源/networking/持久化/工作流改造/回滚 → A1-A5 全覆盖；Phase B 因动 app 发布单独成任务（A3/A4），可独立评审、独立回滚。
- 无占位符：全部命令/镜像 pin 实测或已在本会话验证；LS admin 走 UI 注册（官方行为）而非臆造 env。
- 未决待评审：宿主端口默认 8224/8225、LS/MLflow 后端 SQLite 落卷（vs MySQL）、MLflow artifact 用既有 MinIO 前缀（非新桶）。

## Execution Handoff

- [ ] A1（已就绪文件，待 commit）→ [ ] A2（服务器纯操作）→ 评审点 1（A 段完成、app 未动）→ [ ] A3/A4（Phase B，动 app 发布）→ [ ] A5 预案随行。
