"""MLflow integration tests that do not require a running MLflow server."""

from app.core.config import settings
from app.integrations import mlflow as integration  # MLFLOW-INTEGRATION


def test_mlflow_is_noop_when_tracking_uri_is_empty(monkeypatch):
    monkeypatch.setattr(settings, "mlflow_mode", "off")
    assert integration.start_run("job_test", "training") is None
    integration.record_training(None, {"epochs": 1}, {"loss": 0.1},
                                {"train": [0.1]}, 1, "models/1/weights.pt")
    integration.record_test(None, {"f1": 0.9}, [[1, 0], [0, 1]])
    integration.record_inference(None, {"latency_ms": 1})
    integration.finish_run(None)
