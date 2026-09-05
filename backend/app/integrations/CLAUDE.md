# CLAUDE.md — backend/app/integrations/

可选外部系统集成层。所有集成都是 **best-effort**：外部系统不可用时只记告警，绝不让业务 Job 或请求失败。业务数据库仍是焊缝/数据集/Job 状态的唯一权威。

## 文件

- `__init__.py`：空包。
- `mlflow.py`：MLflow 跟踪集成（2026-08-29，Task 16 真实训练配套）。走公开 `MlflowClient` API：
  - `_client()`：按 `settings.mlflow_mode`（`off`/`embedded`/`server`）创建客户端；`server` 模式无 `mlflow_tracking_uri` 时返回 `None`（不启用）；从 `settings` 注入 `MLFLOW_S3_ENDPOINT_URL`/`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_DEFAULT_REGION`（MinIO 作 artifact store）。**2026-09**：未显式配置 `MLFLOW_S3_ENDPOINT_URL` 时回退用 `minio_server_endpoint or minio_endpoint`（服务端数据面优先内网，双端点内网化，见 `storage/CLAUDE.md`）。任何异常/缺包 → `None` 并告警。
  - `start_run(job_uid, kind, tags)`：建 RUNNING Run（experiment 不存在则创建，`artifact_location=mlflow_artifact_root`）→ 返回 run_id；由 `app/jobs/executor.py` 在模型中心 Job 首次运行时创建，写入 `Job.mlflow_run_id`。
  - `log_params`/`log_metrics`/`log_json_artifact`：逐条 try/except，失败仅告警。
  - `finish_run(run_id, status)`：终止 Run；Job failed 时由执行器调 `finish_run(run_id, "FAILED")`。
  - `record_training`/`record_test`/`record_inference`：训练/测试/推理的打包记录助手，供 `app/services/models.py` 调用。

## 调用链

- 被谁调用：`app/jobs/executor.py`（start_run/finish_run）、`app/services/models.py`（record_training/record_test/record_inference）。
- 调用谁：`app/core/config.py::settings`（mlflow_* 配置）。

## 关键规则/坑

- **best-effort 铁律**：本目录所有对外方法必须 try/except 吞掉异常并 `logger.warning`，不得向上抛，否则会拖垮业务 Job。
- **`mlflow_mode` 默认 `embedded` + `sqlite:///./data/mlflow.db`**：该 sqlite 文件落在**容器临时文件系统**内，容器重启即丢失 MLflow 侧 run 元数据/指标/曲线（业务 DB 的 `Job.mlflow_run_id` 仍在）。生产应设 `MLFLOW_MODE=server`（指向外部 tracking server）或为 `./data` 挂持久卷。
- 新增集成模块同样遵循 best-effort + 不阻塞业务的原则；外部凭据一律走 `settings`（`.env`），不写死代码。
