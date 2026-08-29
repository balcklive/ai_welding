"""CPU Torch real-sample training contract."""

import pytest


pytest.importorskip("torch")


def test_cpu_torch_training_is_deterministic_and_produces_weights():
    from app.services.torch_training import TrainingExample, run

    examples = [
        TrainingExample(i, "train", (float(i), 0, 0, 0, 0, 0, float(i), 1), i % 2, "a" if i % 2 == 0 else "b")
        for i in range(8)
    ] + [
        TrainingExample(i, "val", (float(i), 0, 0, 0, 0, 0, float(i), 1), i % 2, "a" if i % 2 == 0 else "b")
        for i in range(8, 12)
    ]

    first = run(task_id=7, epochs=3, seed=7, examples=examples, classes=["a", "b"])
    second = run(task_id=7, epochs=3, seed=7, examples=examples, classes=["a", "b"])

    assert first.metrics == second.metrics
    assert first.loss_curve == second.loss_curve
    assert len(first.loss_curve["train"]) == 3
    assert len(first.weights) > 100
