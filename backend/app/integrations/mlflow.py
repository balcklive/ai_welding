"""Optional MLflow integration for model-center jobs.

MLflow is used through its public tracking client APIs. The business database
remains authoritative for welding entities and Job state. All methods are
best-effort so an unavailable MLflow server cannot fail a domain job.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import settings


def _client():
    # MLFLOW-INTEGRATION: single boundary for embedded/server/off modes.
    if settings.mlflow_mode == "off":
        return None
    try:
        import mlflow
        from mlflow import MlflowClient

        tracking_uri = settings.mlflow_tracking_uri
        if settings.mlflow_mode == "server" and not tracking_uri:
            return None
        if tracking_uri.startswith("sqlite:///"):
            raw_path = tracking_uri.removeprefix("sqlite:///")
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        mlflow.set_tracking_uri(tracking_uri)
        if settings.mlflow_registry_uri:
            mlflow.set_registry_uri(settings.mlflow_registry_uri)
        s3_endpoint = settings.mlflow_s3_endpoint_url
        if not s3_endpoint and settings.minio_endpoint:
            scheme = "https" if settings.minio_secure else "http"
            # 服务端数据面优先走内网端点（同宿主避免绕公网），未配置回退公网
            endpoint = settings.minio_server_endpoint or settings.minio_endpoint
            s3_endpoint = f"{scheme}://{endpoint}"
        if s3_endpoint:
            os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", s3_endpoint)
        if settings.minio_access_key:
            os.environ.setdefault("AWS_ACCESS_KEY_ID", settings.minio_access_key)
        if settings.minio_secret_key:
            os.environ.setdefault("AWS_SECRET_ACCESS_KEY", settings.minio_secret_key)
        os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
        return MlflowClient(tracking_uri=tracking_uri)
    except ImportError:
        logger.warning("MLflow is configured but the mlflow package is not installed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to create MLflow client: {}", exc)
    return None


def start_run(job_uid: str, kind: str, tags: Mapping[str, Any] | None = None) -> str | None:
    # MLFLOW-INTEGRATION: create the Run before the domain Job handler starts.
    """Create a RUNNING Run and return its id."""
    client = _client()
    if client is None:
        return None
    try:
        import mlflow

        experiment = client.get_experiment_by_name(settings.mlflow_experiment)
        experiment_id = (
            experiment.experiment_id
            if experiment is not None
            else client.create_experiment(
                settings.mlflow_experiment,
                artifact_location=settings.mlflow_artifact_root,
            )
        )
        run = client.create_run(experiment_id, tags={
            "application": "ai-welding",
            "job_uid": job_uid,
            "job_type": kind,
            **{key: str(value) for key, value in (tags or {}).items() if value is not None},
        })
        return run.info.run_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to create MLflow run for {}: {}", job_uid, exc)
        return None


def log_params(run_id: str | None, params: Mapping[str, Any]) -> None:
    # MLFLOW-INTEGRATION: public MlflowClient parameter logging.
    client = _client()
    if client is None or not run_id:
        return
    try:
        for key, value in params.items():
            if value is not None:
                client.log_param(run_id, key, str(value))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to log MLflow params for {}: {}", run_id, exc)


def log_metrics(run_id: str | None, metrics: Mapping[str, Any], step: int = 0) -> None:
    # MLFLOW-INTEGRATION: public MlflowClient metric logging.
    client = _client()
    if client is None or not run_id:
        return
    try:
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                client.log_metric(run_id, key, float(value), step=step)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to log MLflow metrics for {}: {}", run_id, exc)


def log_json_artifact(run_id: str | None, filename: str, value: Any) -> None:
    # MLFLOW-INTEGRATION: JSON evaluation/training artifact logging.
    client = _client()
    if client is None or not run_id:
        return
    try:
        with tempfile.TemporaryDirectory(prefix="aiwelding-mlflow-") as tmp:
            path = Path(tmp) / Path(filename).name
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            client.log_artifact(run_id, str(path), artifact_path="model-center")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to log MLflow artifact for {}: {}", run_id, exc)


def finish_run(run_id: str | None, status: str = "FINISHED") -> None:
    # MLFLOW-INTEGRATION: terminate Run independently from the business Job.
    client = _client()
    if client is None or not run_id:
        return
    try:
        client.set_terminated(run_id, status=status)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to finish MLflow run {}: {}", run_id, exc)


def record_training(run_id: str | None, hyperparams: Mapping[str, Any],
                    metrics: Mapping[str, Any], loss_curve: Any,
                    model_version_id: int, file_key: str | None) -> None:
    log_params(run_id, {**hyperparams, "model_version_id": model_version_id,
                        "model_file_key": file_key})
    log_metrics(run_id, metrics)
    log_json_artifact(run_id, "loss_curve.json", loss_curve)
    log_json_artifact(run_id, "model_artifact.json", {"file_key": file_key})


def record_test(run_id: str | None, metrics: Mapping[str, Any],
                confusion_matrix: list[list[int]]) -> None:
    log_metrics(run_id, metrics)
    log_json_artifact(run_id, "confusion_matrix.json", confusion_matrix)


def record_inference(run_id: str | None, result: Mapping[str, Any]) -> None:
    log_metrics(run_id, {"latency_ms": result.get("latency_ms", 0)})
    log_json_artifact(run_id, "inference_result.json", dict(result))
