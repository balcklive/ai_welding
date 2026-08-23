"""模型包：导出全部 SQLModel 表类。

`from app.models import *` 会导入 23 张表，供 Alembic env.py 绑定 `SQLModel.metadata`。
"""

from .analysis import (
    AlignmentTask,
    Annotation,
    AnnotationTask,
    FeatureExtraction,
    LabelCategory,
    Sample,
    SplitTask,
)
from .data import (
    AuditLog,
    DataRecord,
    DataVersion,
    User,
    ValidationReport,
    ValidationRuleResult,
)
from .datasets import Dataset, DatasetBuildTask, DatasetItem, DatasetVersion
from .jobs import Job
from .models import InferenceTask, Model, ModelVersion, TestTask, TrainingTask

__all__ = [
    # data.py
    "User",
    "DataRecord",
    "DataVersion",
    "ValidationReport",
    "ValidationRuleResult",
    "AuditLog",
    # jobs.py
    "Job",
    # analysis.py
    "AlignmentTask",
    "SplitTask",
    "Sample",
    "AnnotationTask",
    "Annotation",
    "LabelCategory",
    "FeatureExtraction",
    # datasets.py
    "Dataset",
    "DatasetVersion",
    "DatasetItem",
    "DatasetBuildTask",
    # models.py
    "Model",
    "ModelVersion",
    "TrainingTask",
    "TestTask",
    "InferenceTask",
]
