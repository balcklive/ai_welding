"""启动 seed（Task 6）：管理员 + 与前端 mock 对齐的演示数据。

- `seed_admin(session)`：`users.username == settings.admin_username` 不存在时插入管理员
  （display_name="林工"、role="admin"、密码为 `settings.admin_password` 的 argon2 哈希）。
- `seed_demo(session)`：演示数据，数值对齐 `src/App.tsx` 常量（weldRows / VersionPanel /
  Validation / datasetRows / ModelRepository / Annotation）与 `docs/API接口清单.md` §2 实体。
- `seed_all(session)`：`seed_admin` + `seed_demo`，末尾统一 `session.commit()`。**幂等**：
  各实体按业务唯一键跳过已存在（weld 按 `weld_id`、登记按 `registration_no`、
  数据集按 `dataset_no`、模型按 `name`、标签按 `label_categories.name`），重复执行不翻倍。

注意事项（坑/边界）：
- 全部走 ORM 写库，不用 MySQL 特有 SQL；SQLite（测试）与 MySQL（真实启动）均可运行。
- 时间戳统一 UTC aware `datetime`；`Numeric` 列用 `Decimal` 赋值。
- 演示数据数值对齐前端 mock，不追求业务完备；后续 Task 接线时由真实服务接管覆盖。
- 依赖 `settings.admin_username/admin_password`（根 `.env`，默认 admin/admin123，生产必改）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import hash_password
from app.models.analysis import (
    Annotation,
    AnnotationTask,
    LabelCategory,
    Sample,
    SplitTask,
)
from app.models.data import (
    AuditLog,
    DataRecord,
    DataVersion,
    User,
    ValidationReport,
    ValidationRuleResult,
)
from app.models.datasets import Dataset, DatasetVersion
from app.models.jobs import Job
from app.models.models import Model, ModelVersion


def _t(y: int, mo: int, d: int, hh: int, mi: int, ss: int = 0) -> datetime:
    """UTC aware 时间构造。"""
    return datetime(y, mo, d, hh, mi, ss, tzinfo=timezone.utc)


# ── 标签类别（前端 Annotation 组件的 5 个 chip；展示色取自前端缺陷色板） ──
LABEL_CATEGORIES: list[tuple[str, str]] = [
    ("焊瘤", "#5fb8a6"),
    ("气孔", "#2c9caf"),
    ("未熔合", "#f0a34a"),
    ("咬边", "#7ba7c4"),
    ("正常", "#b0c4b8"),
]

# ── 核验规则明细（与 App.tsx Validation 组件 15 项逐字一致；第 9 项「视频帧率稳定性」= 警告） ──
VALIDATION_RULES: list[str] = [
    "图像文件完整性",
    "时序信号连续性",
    "采样频率一致性",
    "起收弧事件完整",
    "电流范围合理性",
    "电压范围合理性",
    "送丝速度缺失值",
    "多模态时间戳",
    "视频帧率稳定性",
    "文件命名规范",
    "焊缝ID唯一性",
    "工艺参数完整性",
    "音频信号质量",
    "红外数据完整性",
    "元数据关联关系",
]

# ── 焊缝演示数据（对齐 App.tsx weldRows / AnalysisSelect / VersionPanel / AdvancedWeldAnalysis） ──
# versions: (version_no, action, operator, created_at, object_keys)；latest 指向最后一个版本。
WELD_DEMO: list[dict] = [
    {
        "weld_id": "WLD-20260815-0248",
        "registration_no": "REG-20260815-00248",
        "weld_name": "MAG 短路过渡 · 典型稳定样本",
        "source": "产线相机 · 03号",
        "collected_at": _t(2026, 8, 15, 9, 42),
        "machine": "Fronius CMT",
        "weld_method": "MAG焊",
        "material": "Q235B",
        "thickness": "6 mm",
        "current_voltage": "180 A / 22 V",
        "sample_rate": "10 kHz",
        "product": "车体侧梁 · A 型试件",
        "modalities": ["video", "timeseries", "audio"],
        "quality": "通过",
        "operator": "林工",
        "storage_bytes": 2576980378,  # ≈ 2.4 GB（总览"单条焊缝最大容量"）
        "versions": [
            (
                "v1.0", "原始数据", "系统导入", _t(2026, 8, 15, 9, 42),
                [
                    "raw/REG-20260815-00248/0001.mp4",
                    "raw/REG-20260815-00248/0002.mp4",
                    "raw/REG-20260815-00248/timeseries.csv",
                    "raw/REG-20260815-00248/audio.wav",
                ],
            ),
            (
                "v1.1", "去噪处理", "林工", _t(2026, 8, 15, 9, 45),
                ["processed/WLD-20260815-0248/denoise/timeseries.csv"],
            ),
            (
                "v1.2", "时间对齐", "算法任务", _t(2026, 8, 15, 9, 48),
                [
                    "processed/WLD-20260815-0248/align/video.mp4",
                    "processed/WLD-20260815-0248/align/current.csv",
                    "processed/WLD-20260815-0248/align/voltage.csv",
                    "processed/WLD-20260815-0248/align/audio.wav",
                    "processed/WLD-20260815-0248/align/tracks.json",
                ],
            ),
            (
                "v1.3", "人工修正", "林工", _t(2026, 8, 15, 10, 6),
                [
                    "processed/WLD-20260815-0248/corrected/sample_0248_0001.mp4",
                    "processed/WLD-20260815-0248/corrected/sample_0248_0002.mp4",
                ],
            ),
        ],
        "validation": True,          # 0248 写核验报告（93.3 / 14 通过 / 1 警告 / 0 失败 / 2.8s）
        "validated_at": _t(2026, 8, 15, 10, 7),
        "annotation": True,          # 0248 写切分+标注任务与 2 个样本标注（标注页演示）
    },
    {
        "weld_id": "WLD-20260815-0247",
        "registration_no": "REG-20260815-00247",
        "weld_name": "熔池异常 · 待复核样本",
        "source": "实训线 · 02号",
        "collected_at": _t(2026, 8, 15, 9, 18),
        "machine": "OTC FD-V8",
        "weld_method": "MIG焊",
        "material": "Q345B",
        "thickness": "8 mm",
        "current_voltage": "220 A / 24 V",
        "sample_rate": "10 kHz",
        "product": "实训线试板",
        "modalities": ["video", "timeseries"],
        "quality": "待复核",
        "operator": "林工",
        "storage_bytes": 1288490189,  # ≈ 1.2 GB
        "versions": [
            (
                "v1.0", "原始数据", "系统导入", _t(2026, 8, 15, 9, 18),
                [
                    "raw/REG-20260815-00247/0001.mp4",
                    "raw/REG-20260815-00247/0002.mp4",
                    "raw/REG-20260815-00247/timeseries.csv",
                ],
            ),
            (
                "v1.1", "去噪处理", "林工", _t(2026, 8, 15, 9, 21),
                ["processed/WLD-20260815-0247/denoise/timeseries.csv"],
            ),
            (
                "v1.2", "时间对齐", "算法任务", _t(2026, 8, 15, 9, 24),
                [
                    "processed/WLD-20260815-0247/align/video.mp4",
                    "processed/WLD-20260815-0247/align/current.csv",
                    "processed/WLD-20260815-0247/align/voltage.csv",
                    "processed/WLD-20260815-0247/align/tracks.json",
                ],
            ),
            (
                "v1.3", "人工修正", "林工", _t(2026, 8, 15, 9, 35),
                ["processed/WLD-20260815-0247/corrected/sample_0247_0001.mp4"],
            ),
        ],
    },
    {
        "weld_id": "WLD-20260814-0246",
        "registration_no": "REG-20260814-00246",
        "weld_name": "红外多模态 · 工艺验证样本",
        "source": "产线相机 · 03号",
        "collected_at": _t(2026, 8, 14, 18, 32),
        "machine": "Kemppi Minarc",
        "weld_method": "TIG焊",
        "material": "304 不锈钢",
        "thickness": "3 mm",
        "current_voltage": "120 A / 14 V",
        "sample_rate": "20 kHz",
        "product": "管件接头",
        "modalities": ["video", "timeseries", "infrared"],
        "quality": "通过",
        "operator": "林工",
        "storage_bytes": 858993459,  # ≈ 0.8 GB
        "versions": [
            (
                "v1.0", "原始数据", "系统导入", _t(2026, 8, 14, 18, 32),
                [
                    "raw/REG-20260814-00246/0001.mp4",
                    "raw/REG-20260814-00246/timeseries.csv",
                    "raw/REG-20260814-00246/infrared.avi",
                ],
            ),
            (
                "v1.1", "去噪处理", "林工", _t(2026, 8, 14, 18, 35),
                ["processed/WLD-20260814-0246/denoise/timeseries.csv"],
            ),
            (
                "v1.2", "时间对齐", "算法任务", _t(2026, 8, 14, 18, 38),
                [
                    "processed/WLD-20260814-0246/align/video.mp4",
                    "processed/WLD-20260814-0246/align/current.csv",
                    "processed/WLD-20260814-0246/align/voltage.csv",
                    "processed/WLD-20260814-0246/align/tracks.json",
                ],
            ),
            (
                "v1.3", "人工修正", "林工", _t(2026, 8, 14, 18, 45),
                ["processed/WLD-20260814-0246/corrected/sample_0246_0001.mp4"],
            ),
        ],
    },
    {
        # 异常样本：按 App.tsx 展示链停在 v1.0（quality=异常，核验失败）。
        "weld_id": "WLD-20260814-0245",
        "registration_no": "REG-20260814-00245",
        "weld_name": "实训线手工样件 · 异常样本",
        "source": "实训线 · 01号",
        "collected_at": _t(2026, 8, 14, 16, 7),
        "machine": "Panasonic YD-500",
        "weld_method": "MAG焊",
        "material": "Q235B",
        "thickness": "10 mm",
        "current_voltage": "260 A / 27 V",
        "sample_rate": "10 kHz",
        "product": "实训线手工样件",
        "modalities": ["video", "audio"],
        "quality": "异常",
        "operator": "林工",
        "storage_bytes": 536870912,  # ≈ 0.5 GB
        "versions": [
            (
                "v1.0", "原始数据", "系统导入", _t(2026, 8, 14, 16, 7),
                [
                    "raw/REG-20260814-00245/0001.mp4",
                    "raw/REG-20260814-00245/audio.wav",
                ],
            ),
        ],
    },
]

# ── 数据集演示数据（对齐 App.tsx datasetRows；split 为 train/val/test） ──
DATASET_DEMO: list[dict] = [
    {
        "dataset_no": "DS-DEFECT-001",
        "name": "焊接缺陷检测集",
        "task": "目标检测",
        "sample_count": 8420,
        "progress": "96.80",
        "status": "可训练",
        "version": "v1.3",
        "split": {"train": 6736, "val": 842, "test": 842},
        "quality": {"repeat_rate": 0.012, "empty_label_rate": 0.0, "missing_dimension_rate": 0.004},
    },
    {
        "dataset_no": "DS-POOL-002",
        "name": "熔池分割数据集",
        "task": "语义分割",
        "sample_count": 5680,
        "progress": "91.20",
        "status": "标注中",
        "version": "v0.8",
        "split": {"train": 4544, "val": 568, "test": 568},
        "quality": {"repeat_rate": 0.021, "empty_label_rate": 0.014, "missing_dimension_rate": 0.008},
    },
    {
        "dataset_no": "DS-QUALITY-003",
        "name": "工艺质量预测集",
        "task": "多模态回归",
        "sample_count": 2140,
        "progress": "100.00",
        "status": "可训练",
        "version": "v2.0",
        "split": {"train": 1712, "val": 214, "test": 214},
        "quality": {"repeat_rate": 0.0, "empty_label_rate": 0.0, "missing_dimension_rate": 0.0},
    },
]

# ── 模型演示数据（对齐 App.tsx ModelRepository） ──
MODEL_DEMO: list[dict] = [
    {
        "name": "焊接异常检测模型",
        "type": "时序分类",
        "description": "基于电流/电压/送丝时序信号的多源异常分类模型",
        "version": "v1.8",
        "metric": {"f1": 0.955},
        "status": "生产候选",
    },
    {
        "name": "熔池分割模型",
        "type": "语义分割",
        "description": "对熔池视频帧做像素级分割的语义分割模型",
        "version": "v2.1",
        "metric": {"miou": 0.912},
        "status": "训练中",
    },
    {
        "name": "质量预测模型",
        "type": "多模态回归",
        "description": "融合多模态特征预测焊接质量的回归模型",
        "version": "v0.9",
        "metric": {"r2": 0.93},
        "status": "实验版本",
    },
]


def seed_admin(session: Session) -> None:
    """无 `users.username == admin_username` 时插入管理员（林工）。"""
    exists = (
        session.exec(select(User).where(User.username == settings.admin_username)).first()
    )
    if exists is not None:
        return
    session.add(
        User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            display_name="林工",
            role="admin",
            avatar=None,
            created_at=datetime.now(timezone.utc),
        )
    )


def seed_demo(session: Session) -> None:
    """演示数据（数值对齐前端 mock）。各子步骤幂等。"""
    _seed_labels(session)
    # Registrations require a dataset; seed datasets before demo weld records.
    _seed_datasets(session)
    _seed_welds(session)
    _seed_models(session)


def seed_all(session: Session) -> None:
    """管理员 + 演示数据，末尾统一 commit。幂等：已存在则跳过。"""
    seed_admin(session)
    seed_demo(session)
    session.commit()


# ── 内部实现 ──────────────────────────────────────────────────────────


def _seed_labels(session: Session) -> None:
    for name, color in LABEL_CATEGORIES:
        exists = session.exec(select(LabelCategory).where(LabelCategory.name == name)).first()
        if exists is not None:
            continue
        session.add(LabelCategory(name=name, color=color))


def _seed_welds(session: Session) -> None:
    admin = (
        session.exec(select(User).where(User.username == settings.admin_username)).first()
    )
    for cfg in WELD_DEMO:
        record = (
            session.exec(select(DataRecord).where(DataRecord.weld_id == cfg["weld_id"])).first()
        )
        if record is not None:
            continue

        default_dataset = session.exec(select(Dataset).order_by(Dataset.id)).first()
        if default_dataset is None:
            raise RuntimeError("无法创建演示登记：默认数据集不存在")
        record = DataRecord(
            weld_id=cfg["weld_id"],
            weld_name=cfg["weld_name"],
            registration_no=cfg["registration_no"],
            source=cfg["source"],
            collected_at=cfg["collected_at"],
            machine=cfg["machine"],
            weld_method=cfg["weld_method"],
            material=cfg["material"],
            thickness=cfg["thickness"],
            current_voltage=cfg["current_voltage"],
            sample_rate=cfg["sample_rate"],
            product=cfg["product"],
            dataset_id=default_dataset.id,
            modalities=cfg["modalities"],
            quality=cfg["quality"],
            operator=cfg["operator"],
            storage_bytes=cfg["storage_bytes"],
            created_at=cfg["collected_at"],
            updated_at=cfg["collected_at"],
        )
        session.add(record)
        session.flush()

        versions = []
        for version_no, action, operator, created_at, object_keys in cfg["versions"]:
            version = DataVersion(
                record_id=record.id,
                version_no=version_no,
                action=action,
                operator=operator,
                object_keys=object_keys,
                created_at=created_at,
            )
            session.add(version)
            session.flush()
            versions.append(version)
        record.latest_version_id = versions[-1].id
        session.add(record)

        if cfg.get("validation"):
            _seed_validation_0248(session, versions[-1], cfg["validated_at"])
        if cfg.get("annotation"):
            _seed_annotation_demo(session, record, versions[-1])
        if admin is not None:
            _seed_audit_logs(session, admin.id, cfg["weld_id"], cfg["registration_no"])


def _seed_validation_0248(session: Session, version: DataVersion, validated_at: datetime) -> None:
    """0248 的核验报告 + 15 条规则明细（第 9 项「视频帧率稳定性」= 警告）。"""
    report = ValidationReport(
        version_id=version.id,
        score=Decimal("93.30"),
        passed=14,
        warning=1,
        failed=0,
        duration=Decimal("2.80"),
        created_at=validated_at,
    )
    session.add(report)
    session.flush()
    for idx, rule_name in enumerate(VALIDATION_RULES):
        is_warning = idx == 8
        session.add(
            ValidationRuleResult(
                report_id=report.id,
                rule_name=rule_name,
                status="warning" if is_warning else "passed",
                message=(
                    "视频帧率存在轻微波动，建议复核"
                    if is_warning
                    else "检查通过 · 结果已记录"
                ),
            )
        )


def _seed_annotation_demo(session: Session, record: DataRecord, version: DataVersion) -> None:
    """给 0248 造切分 + 标注任务与 2 个样本标注（焊瘤 0.94 / 气孔 0.88），供标注页演示。"""
    weld_id = record.weld_id
    suffix = weld_id.split("-")[-1]

    split_job = Job(
        job_uid=f"job_split_{suffix}",
        type="split",
        status="succeeded",
        progress=100,
        result={"sample_count": 248},
        created_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(split_job)
    session.flush()
    split_task = SplitTask(
        job_id=split_job.id,
        version_id=version.id,
        rules={"frequency": "10帧/样本", "event_buffer": 0.20},
        task_format="目标检测",
        sample_count=248,
    )
    session.add(split_task)
    session.flush()

    annot_job = Job(
        job_uid=f"job_annotation_{suffix}",
        type="annotation",
        status="succeeded",
        progress=100,
        created_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(annot_job)
    session.flush()
    annot_task = AnnotationTask(
        job_id=annot_job.id,
        split_task_id=split_task.id,
        name="AN-0248",
        source="split_task",
        created_at=datetime.now(timezone.utc),
    )
    session.add(annot_task)
    session.flush()

    sample_1 = Sample(
        split_task_id=split_task.id,
        annotation_task_id=annot_task.id,
        frame_no=248,
        object_keys=[f"processed/{weld_id}/corrected/sample_0248_0001.mp4"],
        meta={"weld_id": weld_id},
    )
    sample_2 = Sample(
        split_task_id=split_task.id,
        annotation_task_id=annot_task.id,
        frame_no=249,
        object_keys=[f"processed/{weld_id}/corrected/sample_0248_0002.mp4"],
        meta={"weld_id": weld_id},
    )
    session.add(sample_1)
    session.add(sample_2)
    session.flush()

    now = datetime.now(timezone.utc)
    session.add(
        Annotation(
            sample_id=sample_1.id,
            category="焊瘤",
            box=[210, 140, 96, 72],
            confidence=Decimal("0.940"),
            annotator="林工",
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        Annotation(
            sample_id=sample_2.id,
            category="气孔",
            box=[380, 210, 74, 58],
            confidence=Decimal("0.880"),
            annotator="林工",
            created_at=now,
            updated_at=now,
        )
    )


def _seed_audit_logs(
    session: Session, admin_id: int, weld_id: str, registration_no: str
) -> None:
    """若干审计日志（create/validate/export），用户为管理员。"""
    now = datetime.now(timezone.utc)
    entries = [
        AuditLog(
            user_id=admin_id, action="create", resource_type="weld", resource_id=weld_id,
            detail={"registration_no": registration_no, "action": "登记原始数据"}, created_at=now,
        ),
        AuditLog(
            user_id=admin_id, action="validate", resource_type="weld", resource_id=weld_id,
            detail={"score": "93.3", "result": "通过"}, created_at=now,
        ),
        AuditLog(
            user_id=admin_id, action="export", resource_type="dataset",
            resource_id="DS-DEFECT-001", detail={"name": "焊接缺陷检测集"}, created_at=now,
        ),
        AuditLog(
            user_id=admin_id, action="create", resource_type="model",
            resource_id="焊接异常检测模型", detail={"version": "v1.8"}, created_at=now,
        ),
    ]
    for entry in entries:
        session.add(entry)


def _seed_datasets(session: Session) -> None:
    for cfg in DATASET_DEMO:
        ds = session.exec(select(Dataset).where(Dataset.dataset_no == cfg["dataset_no"])).first()
        if ds is not None:
            continue
        ds = Dataset(
            dataset_no=cfg["dataset_no"],
            name=cfg["name"],
            task=cfg["task"],
            sample_count=cfg["sample_count"],
            progress=Decimal(cfg["progress"]),
            status=cfg["status"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(ds)
        session.flush()
        version = DatasetVersion(
            dataset_id=ds.id,
            version_no=cfg["version"],
            split=cfg["split"],
            item_count=cfg["sample_count"],
            quality=cfg["quality"],
            created_at=datetime.now(timezone.utc),
        )
        session.add(version)
        session.flush()
        version.snapshot_id = f"datasets/{version.id}/snapshot.json"
        ds.current_version_id = version.id
        session.add(ds)


def _seed_models(session: Session) -> None:
    for cfg in MODEL_DEMO:
        model = session.exec(select(Model).where(Model.name == cfg["name"])).first()
        if model is not None:
            continue
        model = Model(name=cfg["name"], type=cfg["type"], description=cfg["description"])
        session.add(model)
        session.flush()
        version = ModelVersion(
            model_id=model.id,
            version_no=cfg["version"],
            metric=cfg["metric"],
            status=cfg["status"],
            created_at=datetime.now(timezone.utc),
        )
        session.add(version)
        session.flush()
        version.file_key = f"models/{version.id}/weights.pt"
        session.add(version)
