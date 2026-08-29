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

from sqlmodel import Session, select

from app.core.config import settings
from app.models.analysis import Annotation, Sample
from app.models.data import DataVersion
from app.models.datasets import DatasetItem


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


def load_real_examples(session: Session, dataset_version_id: int, storage) -> tuple[list[TrainingExample], list[str]]:
    """Load the fixed dataset snapshot as two classes: normal/defect."""
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
    sample_ids = [sample.id for _item, sample in rows if sample.id is not None]
    annotations = session.exec(
        select(Annotation).where(Annotation.sample_id.in_(sample_ids)).order_by(Annotation.id)
    ).all()
    by_sample: dict[int, list[Annotation]] = {}
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
        sample_annotations = by_sample.get(sample.id, [])
        label_name = "缺陷" if any(a.category for a in sample_annotations) else "正常"
        examples.append(TrainingExample(sample.id, item.split, _features_from_sample(storage, sample, session, feature_cache), label_ids[label_name], label_name))
    if not examples:
        raise ValueError("数据集版本没有可训练的真实样本")
    return examples, label_names


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


def run(task_id: int, epochs: int, seed: int, examples: list[TrainingExample], classes: list[str]) -> CpuTrainingResult:
    """Train a small multi-class classifier on real CPU-loaded examples."""
    import torch
    from torch import nn
    if len(classes) < 2 or not examples:
        raise ValueError("真实训练至少需要两个类别和一个样本")
    torch.set_num_threads(max(1, settings.torch_cpu_threads))
    torch.manual_seed(seed)
    device = torch.device("cpu")
    train = [e for e in examples if e.split == "train"]
    val = [e for e in examples if e.split in {"val", "test"}]
    if not train or not val:
        raise ValueError("真实数据必须同时包含 train 和 val/test split")
    train_x = torch.tensor([e.features for e in train], dtype=torch.float32, device=device)
    train_y = torch.tensor([e.label for e in train], dtype=torch.long, device=device)
    val_x = torch.tensor([e.features for e in val], dtype=torch.float32, device=device)
    val_y = torch.tensor([e.label for e in val], dtype=torch.long, device=device)
    model = nn.Sequential(nn.Linear(8, 16), nn.ReLU(), nn.Linear(16, len(classes))).to(device)
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
    torch.save({"task_id": task_id, "framework": "torch", "device": "cpu", "model_state_dict": model.state_dict(), "input_dim": 8, "classes": classes, "source": "dataset_items/samples/annotations"}, buffer)
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
