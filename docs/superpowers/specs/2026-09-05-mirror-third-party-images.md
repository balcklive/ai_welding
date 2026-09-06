# 2026-09-05 第三方镜像 mirror 到 ACR + 服务器验证实施计划

> 背景：生产机实测（`182.61.59.135:8222`，wwwroot，Docker 29.1.3，`ai-welding` Up/healthy @8223）：
> - **Label Studio**（Docker Hub `heartexlabs/label-studio`）直拉被 `connection reset`（换 IP 复现 2 次）→ **必须 mirror 到 ACR**；
> - **MLflow**（GHCR `ghcr.io/mlflow/mlflow`）服务器直拉成功（369MB/247s），smoke `/health`=OK → **无需 mirror，可直拉**；
> - 本机与服务器都无法访问 Docker Hub、本地无 ACR 登录 → mirror 唯一可行执行点 = **GitHub Actions runner**。
>
> 详细架构与部署拓扑见 spec `docs/superpowers/specs/2026-09-05-mlflow-dataset-annotation-design.md` §4。

## 目标
1. 新增镜像 mirror workflow，把 LS（必需）与 MLflow（可选）官方镜像搬进 ACR，供生产机稳定拉取。
2. 服务器上做 mirror 后的验证清单（pull → smoke → 清理），确认 LS 也能在目标机跑起来。
3. 为后续 Docker Compose 部署（LS/MLflow/app）备好可用的 ACR 镜像引用。

## 版本 pin（实测确认）
| 组件 | 上游 | tag / digest | 说明 |
|---|---|---|---|
| Label Studio | `heartexlabs/label-studio`（Docker Hub） | `1.23.0` | 2026-03 发布；mirror 前可用 Docker Hub API 复核是否更新 |
| MLflow server | `ghcr.io/mlflow/mlflow`（GHCR） | `3.16.0`；digest `sha256:e72e134e…212e998` | 生产机直拉即可；ACR mirror 仅可选 |

## 一、新增 mirror workflow（已完成草稿）
文件：`.github/workflows/mirror-3rd-party-images.yml`
- `workflow_dispatch` 触发；输入 `label_studio_tag`（默认 `1.23.0`）、`mirror_mlflow`（默认 false）、`mlflow_tag`（默认 `3.16.0`）。
- `mirror-label-studio` job：ACR 登录 → `docker pull heartexlabs/label-studio:<tag>` → tag `crpi-…/aliyun_kaka/label-studio:<tag>` → push。
- `mirror-mlflow` job（`if: inputs.mirror_mlflow`）：按 digest pull GHCR → tag `…/aliyun_kaka/mlflow:v<tag>` → push。
- 复用 `ALIYUN_ACR_*` secrets（`deploy-docker.yml` 已有）。
- 不在 main 自动发布链，独立手动触发。

**状态（2026-09-05 已实测）**：
- [x] workflow 推送 main 并手动触发成功（run `33941917294`，1m15s）；`mirror-label-studio` 全绿。镜像已自动建出 ACR 仓库 `aliyun_kaka/label-studio:1.23.0`。
- [x] 服务器 ACR 拉取 + smoke 均通过（见 §二）。ACR 侧拉取 digest `sha256:7389f22205ffe35131fb340b4e9b1f81d66ae1eb7d66b6004ddd25aa5f90880b`（上游 Docker Hub digest `sha256:aa461572e8f9d86a1bf9520c1db620204e86160fd2f80dd7e9d40ac84a8828ea`）。

## 二、服务器验证清单（mirror 后执行，目标机 182.61.59.135:8222）
> 全程只动临时容器/镜像，**不触碰 `ai-welding` 生产容器**（当前 Up/healthy @8223）。
> 磁盘当前 78G 空闲；内存可用 6.8G。

- [x] 1. 服务器从 ACR `docker pull …/aliyun_kaka/label-studio:1.23.0` **成功**（73s，370MB；对比 Docker Hub 直拉 `connection reset`）。
- [x] 2. LS 临时 smoke：`docker run … -p 127.0.0.1:18080:8080` 首启建库约 100s 后 `/health`=`{"status":"UP"}`，`/version`=`1.23.0 Community`（当前非 outdated）。
- [x] 3. 验证完毕 `docker rm -f ls-smoke` 已清理；LS/MLflow 镜像保留在服务器（磁盘富余 78G，后续 compose 直接复用，无需重拉）。
- [ ] 4. （可选，若走 ACR）MLflow：`docker pull crpi-…/aliyun_kaka/mlflow:v3.16.0` + 同 smoke——默认不 mirror，服务器直拉 GHCR 已验证（369MB/247s + `/health`=OK）。
- [x] 5. 生产容器未受影响：`ai-welding` Up 6 天 healthy。

## 三、后续（不在本计划，属于 compose 部署批次）
- 用 ACR 镜像引用写 `docker-compose.yml`：`app`（ACR build+push）、`label-studio`（ACR `:1.23.0`）、`mlflow`（直拉 GHCR 或 ACR）。
- `deploy-docker.yml` 从单容器 `docker run` 迁移到 compose（保留 app 蓝绿/readiness/回滚），见 spec §4.2。

## 验收标准
1. `mirror-3rd-party-images.yml` 在 Actions 手动触发能成功把 LS 推上 ACR，log 输出 ACR digest。
2. 服务器从 ACR 拉 LS 成功且 smoke `/health` 通过，生产 `ai-welding` 不受影响。
3. 所有临时容器清理，无残留。
