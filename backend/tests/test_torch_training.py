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


# ── 训练前的逐维标准化（2026-10） ─────────────────────────────────────
#
# 背景：特征向量存的是**原始值**（`电流均值` 这类维度是 200 量级），直接进 `Linear`
# 会让首轮 logits 爆掉——线上实测 val loss 起始 1.06e12。修法是训练前按 **train 划分**
# 拟合逐维 mean/std。这里钉住两件不能退让的事：**只在 train 上拟合**（否则泄漏），
# 以及**是跨样本拟合**（不是对单个向量做 z-score，那是切片级刻意避免的）。


def test_fit_standardizer_uses_train_rows_and_guards_zero_variance():
    from app.services.torch_training import _fit_standardizer

    train = [(0.0, 5.0, 7.0), (2.0, 5.0, 9.0), (4.0, 5.0, 11.0)]
    means, stds = _fit_standardizer(train)
    assert means == [2.0, 5.0, 9.0]
    assert stds[0] == pytest.approx((8.0 / 3) ** 0.5)   # 总体标准差，不是样本标准差
    assert stds[2] == pytest.approx((8.0 / 3) ** 0.5)
    # 常量维（train 上方差为 0）→ std 取 1，只做中心化，绝不除以 0
    assert stds[1] == 1.0
    # 单样本 train：全部维度方差为 0，仍然不炸
    means1, stds1 = _fit_standardizer([(3.0, -1.0)])
    assert means1 == [3.0, -1.0] and stds1 == [1.0, 1.0]


def test_standardizer_is_fit_on_train_only_no_leakage():
    """**验证集不参与拟合**：离 train 均值很远的 val 点必须仍然很远（不被"白化"）。

    如果用全量拟合，那个 val 点会被拉回 0 附近——那正是把验证集分布信息漏进训练的表现。
    """
    from app.services.torch_training import _apply_standardizer, _fit_standardizer

    train = [(0.0,), (1.0,), (2.0,)]
    means, stds = _fit_standardizer(train)
    far = _apply_standardizer((1000.0,), means, stds)
    assert far[0] > 100, far          # 用 train 的统计量变换 → 仍然是个大数
    assert _apply_standardizer((1.0,), means, stds)[0] == pytest.approx(0.0)  # train 均值点 → 0


def test_run_standardizes_so_first_loss_is_sane_and_stats_are_persisted():
    """**这是本改动的验收标准**：含 200 量级维度的特征，首轮 train loss 必须是"正常量级"。

    改动前：原始值直接进 Linear → 首轮 logits 巨大 → 交叉熵上到千/万亿量级。
    改动后：按 train 标准化 → 首轮 loss 落在个位数/十位数。
    """
    import io
    import math

    import torch

    from app.services.torch_training import TrainingExample, run

    # 第 0 维是"电流均值"那种 200 量级；第 1 维是小量级 —— 尺度差 4 个数量级的典型形态
    def row(index: int, label: int) -> tuple[float, ...]:
        return (200.0 + index, 0.01 * index, 15.0, 8.0, float(index), 1.0, 0.5, 0.25)

    examples = (
        [TrainingExample(i, "train", row(i, i % 2), i % 2, "a" if i % 2 == 0 else "b") for i in range(8)]
        + [TrainingExample(i, "val", row(i, i % 2), i % 2, "a" if i % 2 == 0 else "b") for i in range(8, 12)]
    )
    result = run(task_id=11, epochs=3, seed=11, examples=examples, classes=["a", "b"])

    first_loss = result.loss_curve["train"][0]
    assert math.isfinite(first_loss) and first_loss < 100, result.loss_curve
    assert all(math.isfinite(v) for v in result.loss_curve["train"] + result.loss_curve["val"])

    saved = torch.load(io.BytesIO(result.weights), weights_only=False)
    assert saved["feature_scaling"] == "train_split_zscore"
    assert len(saved["feature_mean"]) == 8 and len(saved["feature_std"]) == 8
    # 拟合的均值就是 train 那 8 条第 0 维的平均（200..207 → 203.5），证明用的是 train
    assert saved["feature_mean"][0] == pytest.approx(203.5)
    # 常量维的 std 被兜成 1（不是 0，否则除零）
    assert all(std > 0 for std in saved["feature_std"])
