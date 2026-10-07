"""CPU-only Torch training over dataset samples stored in MinIO.

The feature adapter converts the first supported image/CSV/JSON object of
each Sample into eight numeric features. Labels are read from Annotation rows.
This is real data plumbing; a future detector can replace the classifier
without changing Job or MLflow integration.
"""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import PurePosixPath

from loguru import logger
from sqlmodel import Session, select

from app.core.config import settings
from app.models.analysis import Annotation, Sample
from app.models.data import DataVersion
from app.models.datasets import DatasetItem

#: 缺陷类别白名单（决策 6 / 验证 §2）：只把这些类别折叠为「缺陷」；熔池/正常等非缺陷剔除，
#: 避免"有非缺陷标注（熔池）的样本被误折为缺陷"污染二分类训练。统计口径未焊透/焊穿亦属缺陷，
#: 一并列出（若出现在标注中则折叠）。
DEFECT_LABELS = frozenset({"焊瘤", "气孔", "未熔合", "咬边", "未焊透", "焊穿"})


@dataclass(frozen=True)
class TrainingExample:
    sample_id: int
    split: str
    features: tuple[float, ...]
    label: int
    label_name: str


@dataclass
class CpuTrainingResult:
    metrics: dict[str, float]
    loss_curve: dict[str, list[float]]
    weights: bytes
    classes: list[str]
    sample_count: int


def load_real_examples(
    session: Session, dataset_version_id: int, storage
) -> tuple[list[TrainingExample], list[str], str]:
    """Load the fixed dataset snapshot as two classes: normal/defect.

    返回 `(examples, label_names, feature_kind)`；`feature_kind` ∈ `slice_v1` | `legacy_summary`。

    **特征口径按成员全有/全无二选一，绝不混用**（混用会让同一批样本维度都不一致）：
    - 全有 `dataset_items.features`（构建时冻结的切片级 36 维）→ `slice_v1`，训练读快照；
    - 全无（本特性之前建的存量版本）→ `legacy_summary`，走旧的"按一个文件现算 8 维"口径，
      **存量数据集因此零改动继续可训**；
    - 部分有 → **拒绝**，并点名缺哪些（构建时没做切片特征提取）。
    """
    rows = session.exec(
        select(DatasetItem, Sample)
        .join(Sample, Sample.id == DatasetItem.sample_id)
        .where(
            DatasetItem.dataset_version_id == dataset_version_id,
            DatasetItem.split.in_(["train", "val"]),
        )
        .order_by(DatasetItem.id)
    ).all()
    if not rows:
        raise ValueError("数据集版本没有真实样本，无法开始训练")
    # 特征口径：全有 / 全无 / 混用（见 docstring）。**不静默混用**——两种口径的向量长度
    # 都不一样，混进同一批只会在 torch 张量化时报一个看不懂的形状错误。
    frozen_count = sum(1 for item, _ in rows if item.features is not None)
    if frozen_count == len(rows):
        feature_kind = "slice_v1"
    elif frozen_count == 0:
        feature_kind = "legacy_summary"
        logger.warning(
            "Dataset version {} has no frozen slice features (built before §3.28); "
            "falling back to the legacy per-sample 8-dim summary — the training input "
            "is NOT the slice-level feature vector for this version.",
            dataset_version_id,
        )
    else:
        missing = [item.sample_id for item, _ in rows if item.features is None][:5]
        raise ValueError(
            f"该数据集版本有 {len(rows) - frozen_count}/{len(rows)} 个成员缺少切片特征"
            f"（构建时未提取，如样本 {missing}），无法用统一输入训练；"
            "请对分段任务执行切片特征提取后重建该版本"
        )
    # T16.1：**优先读构建时冻结的标注快照**（`dataset_items.annotations`）——版本构建之后
    # 继续改标注不该改变同一版本的训练输入。只在快照缺失（T16 之前建的版本）时才现查
    # `annotations` 表，保持旧行为。
    needs_live_annotations = any(item.annotations is None for item, _ in rows)
    by_sample: dict[int, list[Annotation]] = {}
    if needs_live_annotations:
        # R4：**不静默**——历史版本（T16 之前构建）没有标注快照，只能现查当下标注，训练输入
        # 因此不可复现。版本详情接口把该事实标成 `annotations_frozen=false`，这里再留一条日志，
        # 便于排查"同一个版本两次训练结果不一样"。
        logger.warning(
            "Dataset version {} has members without a frozen annotation snapshot "
            "(built before T16); falling back to the live annotations table — "
            "the training input is NOT reproducible for this version.",
            dataset_version_id,
        )
        sample_ids = [sample.id for _item, sample in rows if sample.id is not None]
        annotations = session.exec(
            select(Annotation).where(Annotation.sample_id.in_(sample_ids)).order_by(Annotation.id)
        ).all()
        for annotation in annotations:
            by_sample.setdefault(annotation.sample_id, []).append(annotation)
    # REAL-DATA-LABELING: this first runnable baseline intentionally collapses
    # all annotated categories into defect and empty annotations into normal.
    label_names = ["正常", "缺陷"]
    label_ids = {name: index for index, name in enumerate(label_names)}
    examples: list[TrainingExample] = []
    feature_cache: dict[str, tuple[float, ...]] = {}
    for item, sample in rows:
        if sample.id is None:
            continue
        # 冻结快照优先；缺失则回退现查（见上面的 needs_live_annotations）
        entries = (
            [{"category": a.category} for a in by_sample.get(sample.id, [])]
            if item.annotations is None
            else item.annotations
        )
        # 段级标注（v3）在快照里直接带结论 `label`，**优先认它**；旧标注按类别白名单折叠
        # （只认白名单内的类别为缺陷，熔池/正常等非缺陷剔除——决策 6）。
        label_name = "缺陷" if any(_is_defect_entry(e) for e in entries) else "正常"
        # 冻结的切片向量优先（构建时写死的那份）；存量版本才回落"按一个文件现算 8 维"。
        features = (
            tuple(float(value) for value in (item.features.get("values") or []))
            if feature_kind == "slice_v1"
            else _features_from_sample(storage, sample, session, feature_cache)
        )
        examples.append(TrainingExample(sample.id, item.split, features, label_ids[label_name], label_name))
    if not examples:
        raise ValueError("数据集版本没有可训练的真实样本")
    return examples, label_names, feature_kind


def _is_defect_entry(entry: dict) -> bool:
    """快照条目是否代表缺陷。

    段级标注（`sample_annotations`，kind=`segment_class`）带权威结论 `label`，
    **直接采信**——词表里加一个自定义缺陷类别（名字不在 `DEFECT_LABELS` 里）时，
    按名字折叠会把结论静默折反。旧标注（框/时序区间/多边形）没有 `label`，仍按
    `DEFECT_LABELS` 白名单折叠。
    """
    label = entry.get("label")
    if label in ("defect", "normal"):
        return label == "defect"
    return str(entry.get("category")) in DEFECT_LABELS


def _features_from_sample(storage, sample: Sample, session: Session, cache: dict[str, tuple[float, ...]]) -> tuple[float, ...]:
    supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".csv", ".json"}
    keys = list(sample.object_keys or [])
    # REAL-DATA-COMPAT: older dataset snapshots stored only version_id/video_key
    # in Sample.meta; recover the original uploaded MinIO object keys.
    meta = sample.meta or {}
    version_id = meta.get("version_id")
    if not keys and version_id is not None:
        version = session.get(DataVersion, int(version_id))
        keys = list(version.object_keys or []) if version is not None else []
    preferred_suffixes = [".jpg", ".jpeg", ".png", ".webp", ".bmp"] if meta.get("mode") == "video" else [".csv", ".json"]
    key = next((str(key) for suffix in preferred_suffixes for key in keys if PurePosixPath(str(key)).suffix.lower() == suffix), None)
    if key is None:
        key = next((str(key) for key in keys if PurePosixPath(str(key)).suffix.lower() in supported), None)
    if key is None:
        raise ValueError(f"样本 {sample.id} 没有支持的真实输入文件（当前支持 image/CSV/JSON）")
    if key in cache:
        return cache[key]
    try:
        payload = storage.get_object(key)
    except Exception as exc:
        raise ValueError(f"样本 {sample.id} 的对象无法从 MinIO 读取: {key}") from exc
    suffix = PurePosixPath(key).suffix.lower()
    try:
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            features = _image_features(payload)
        elif suffix == ".csv":
            features = _summary_features(_csv_values(payload))
        else:
            features = _summary_features(_json_values(payload))
        cache[key] = features
        return features
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"样本 {sample.id} 的真实文件解析失败: {key}") from exc


def _image_features(payload: bytes) -> tuple[float, ...]:
    from PIL import Image
    with Image.open(io.BytesIO(payload)) as image:
        values = [pixel / 255.0 for pixel in image.convert("L").resize((32, 32)).getdata()]
    return _summary_features(values)


def _csv_values(payload: bytes) -> list[float]:
    values: list[float] = []
    for row in csv.reader(io.StringIO(payload.decode("utf-8-sig"))):
        for value in row:
            try:
                number = float(value.strip())
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number)
    if not values:
        raise ValueError("CSV 中没有有限数值")
    return values


def _json_values(payload: bytes) -> list[float]:
    value = json.loads(payload.decode("utf-8"))
    values: list[float] = []
    def visit(node) -> None:
        if isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(node):
            values.append(float(node))
        elif isinstance(node, dict):
            for child in node.values(): visit(child)
        elif isinstance(node, list):
            for child in node: visit(child)
    visit(value)
    if not values:
        raise ValueError("JSON 中没有有限数值")
    return values


def _summary_features(values: list[float]) -> tuple[float, ...]:
    if not values:
        raise ValueError("真实样本没有数值特征")
    ordered = sorted(values)
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    def percentile(q: float) -> float:
        index = (len(ordered) - 1) * q
        low, high = math.floor(index), math.ceil(index)
        return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (index - low)
    return tuple(float(value) for value in (mean, stdev, ordered[0], percentile(.25), percentile(.5), percentile(.75), ordered[-1], sum(value != mean for value in values) / len(values)))


def _fit_standardizer(train_features: list[tuple[float, ...]]) -> tuple[list[float], list[float]]:
    """按 **train 划分**拟合逐维 mean/std。

    两条不可退让的性质：

    1. **只在 train 上拟合**。用全量（含 val/test）拟合会把验证集的分布信息漏进训练——
       数据泄漏的一种，指标会虚高。val/test 一律用 train 的统计量**变换**，不参与拟合。
    2. **跨样本拟合，而不是对单个向量做**。`features._normalize` 那种"对单个向量"的
       Z-Score 正是切片级刻意不做的（会把每片各自减均值、抹掉区分切片的那批量）——
       两者不是一回事，别混。

    退化维度（train 上方差 ≈ 0）标准差取 1、只做中心化，避免除以 0。
    """
    count = len(train_features)
    dim = len(train_features[0])
    means = [sum(row[i] for row in train_features) / count for i in range(dim)]
    stds: list[float] = []
    for i in range(dim):
        variance = sum((row[i] - means[i]) ** 2 for row in train_features) / count
        stds.append(math.sqrt(variance) if variance > 1e-12 else 1.0)
    return means, stds


def _apply_standardizer(
    features: tuple[float, ...], means: list[float], stds: list[float]
) -> tuple[float, ...]:
    return tuple((value - mean) / std for value, mean, std in zip(features, means, stds))


def run(
    task_id: int,
    epochs: int,
    seed: int,
    examples: list[TrainingExample],
    classes: list[str],
    feature_kind: str = "legacy_summary",
) -> CpuTrainingResult:
    """Train a small multi-class classifier on real CPU-loaded examples.

    **输入维度从数据来**（不再是写死的 8）：切片级特征 36 维、存量版本的旧口径 8 维，
    同一份代码都要能跑。维度不一致直接报错——那说明同一批里混用了两种特征口径。

    **训练前按 train 划分做逐维标准化**：特征向量存的是**原始值**
    （`sample_features.normalization` 恒为 `无`，见 §6），"电流均值"这类维度是 200 量级，
    直接进 `Linear` 会让首轮 logits 爆掉、交叉熵上到 1e12 量级（线上实测：val loss
    起始 1.06e12）。拟合出的 mean/std 存进权重文件，将来做推理必须用**同一组**统计量
    预处理，否则输入分布对不上。
    """
    import torch
    from torch import nn
    if len(classes) < 2 or not examples:
        raise ValueError("真实训练至少需要两个类别和一个样本")
    torch.set_num_threads(max(1, settings.torch_cpu_threads))
    torch.manual_seed(seed)
    device = torch.device("cpu")
    input_dim = len(examples[0].features)
    if any(len(example.features) != input_dim for example in examples):
        raise ValueError("训练样本特征维度不一致（同一数据集版本里混用了不同特征口径）")
    train = [e for e in examples if e.split == "train"]
    val = [e for e in examples if e.split in {"val", "test"}]
    if not train or not val:
        raise ValueError("真实数据必须同时包含 train 和 val/test split")
    feature_means, feature_stds = _fit_standardizer([e.features for e in train])
    train_x = torch.tensor(
        [_apply_standardizer(e.features, feature_means, feature_stds) for e in train],
        dtype=torch.float32, device=device,
    )
    train_y = torch.tensor([e.label for e in train], dtype=torch.long, device=device)
    val_x = torch.tensor(
        [_apply_standardizer(e.features, feature_means, feature_stds) for e in val],
        dtype=torch.float32, device=device,
    )
    val_y = torch.tensor([e.label for e in val], dtype=torch.long, device=device)
    model = nn.Sequential(nn.Linear(input_dim, 16), nn.ReLU(), nn.Linear(16, len(classes))).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.08)
    criterion = nn.CrossEntropyLoss()
    train_curve: list[float] = []
    val_curve: list[float] = []
    for _epoch in range(max(1, epochs)):
        model.train(); optimizer.zero_grad(set_to_none=True)
        train_loss = criterion(model(train_x), train_y); train_loss.backward(); optimizer.step()
        model.eval()
        with torch.no_grad(): val_loss = criterion(model(val_x), val_y)
        train_curve.append(round(float(train_loss.item()), 6)); val_curve.append(round(float(val_loss.item()), 6))
    with torch.no_grad(): predictions = model(val_x).argmax(dim=1)
    correct = int((predictions == val_y).sum().item())
    accuracy = correct / max(1, len(val_y))
    precision, recall, f1 = _macro_metrics(predictions, val_y, len(classes))
    buffer = io.BytesIO()
    torch.save({"task_id": task_id, "framework": "torch", "device": "cpu", "model_state_dict": model.state_dict(), "input_dim": input_dim, "feature_kind": feature_kind, "feature_scaling": "train_split_zscore", "feature_mean": feature_means, "feature_std": feature_stds, "classes": classes, "source": "dataset_items/samples/annotations"}, buffer)
    metrics = {"mAP50": round(accuracy, 4), "accuracy": round(accuracy, 4), "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
    return CpuTrainingResult(metrics, {"train": train_curve, "val": val_curve}, buffer.getvalue(), classes, len(examples))


def _macro_metrics(predictions, labels, class_count: int) -> tuple[float, float, float]:
    precisions: list[float] = []; recalls: list[float] = []
    for index in range(class_count):
        tp = int(((predictions == index) & (labels == index)).sum().item())
        fp = int(((predictions == index) & (labels != index)).sum().item())
        fn = int(((predictions != index) & (labels == index)).sum().item())
        precisions.append(tp / max(1, tp + fp)); recalls.append(tp / max(1, tp + fn))
    precision = sum(precisions) / class_count; recall = sum(recalls) / class_count
    return precision, recall, 2 * precision * recall / max(1e-9, precision + recall)
