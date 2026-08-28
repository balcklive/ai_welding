"""split job handler（Task 14）：数据切分（模拟）。

编排为真实异步：Job 状态/进度/结果回填与 MinIO 产物对象键为真，计算内核为演示
（`docs/开发规范.md` §3.1）。按切分规则 `{fixed_rate, keep_event_buffer, task_format}`
生成 `sample_count` 个样本（`samples` 表），`object_keys` 用
`processed/{weld_id}/split/...`，回填 `SplitTask.sample_count` 与 `job.result`。

领域逻辑直接放本模块（任务清单只规划了 `jobs/split.py`，无独立 service）：
- `simulate_split(session, task, job)`：进度逐步 → 建样本 → 回填 sample_count + result。
- `@register_handler("split")` 注册到执行器注册表。

坑/边界：
- `sample_count = max(1, total_frames // fixed_rate)`，`total_frames = int(DURATION*1000)`，
  `DURATION` 取自 `services/signals.py`（5.42s → 5420 帧，确定性）。fixed_rate 为「帧/样本」。
- 样本对象键需要 `sample.id`（flush 后才有），故逐样本 add + flush 后回填 object_keys。
- 进度逐次 `session.commit()`（轮询可见）；最终事务（样本 + task.sample_count +
  job.result）由执行器在 handler 返回后统一 commit。
"""

from __future__ import annotations

import io
import json
import time

from loguru import logger

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.analysis import Sample, SplitTask
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services.jobs import mark_succeeded
from app.services.signals import DURATION

#: 参考时长（s）= 信号生成器时长（signals.DURATION=5.42，1000Hz → 5420 帧），与前端一致。
_REF_DURATION_S = DURATION

#: 结果 JSON 内 `samples[]` 的展示上限。切分样本可上千（fixed_rate=1 → 5420），全量塞进
#: `job.result` 会让 `GET /split-tasks/{id}` 与 `GET /jobs/{id}` 每次轮询回传 ~500KB；
#: 前端只消费 `sample_count`（App.tsx Alignment splitOnly），故 `samples` 只保留前 N 条作预览，
#: 全量样本以 `samples` 表（split_task_id）为准，不落结果。
_MAX_RESULT_SAMPLES = 50

#: 进度逐步递增点（0→100）。步间 commit + 小睡，让轮询/前端能看到 progress 变化。
_PROGRESS_STEPS: tuple[int, ...] = (20, 40, 60, 80, 100)
_PROGRESS_SLEEP: float = 0.005


@register_handler("split")
def handle(job_id: int, session: Session) -> None:
    """数据切分（模拟）：按规则生成样本并回填任务/Job 结果。

    由执行器在独立 `Session`（`SessionLocal`）内调用；失败时执行器兜底 `mark_failed`。
    """
    task = session.exec(
        select(SplitTask).where(SplitTask.job_id == job_id)
    ).first()
    if task is None:
        raise ValueError(f"切分任务不存在: job_id={job_id}")
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job 不存在: id={job_id}")
    simulate_split(session, task, job)


def simulate_split(session: Session, task: SplitTask, job: Job) -> dict:
    """模拟执行一次切分任务，返回写入 `job.result` 的 dict。

    步骤：
    1. 解析规则 `fixed_rate`（帧/样本，>=1）与版本 → 推导 `sample_count`；
    2. 进度逐步 0→100（逐次 commit + 小睡，轮询可见）；
    3. 逐样本建 `Sample` 行（frame_no 0..n，object_keys 用 `processed/{weld_id}/split/...`）；
    4. 回填 `task.sample_count`；`mark_succeeded(job, result)`。
    commit 由调用方（执行器）在返回后统一提交。
    """
    rules = dict(task.rules or {})
    fixed_rate = rules.get("fixed_rate")
    stride = rules.get("stride", fixed_rate)
    if not isinstance(fixed_rate, int) or fixed_rate < 1:
        raise ValueError(f"切分规则 fixed_rate 需为 >=1 的整数，当前: {fixed_rate!r}")
    if not isinstance(stride, int) or stride < 1:
        raise ValueError(f"切分规则 stride 需为 >=1 的整数，当前: {stride!r}")

    version = session.get(DataVersion, task.version_id)
    if version is None:
        raise ValueError(f"切分任务引用的版本不存在: version_id={task.version_id}")
    record = session.get(DataRecord, version.record_id)
    if record is None:
        raise ValueError(f"切分任务引用的焊缝不存在: record_id={version.record_id}")

    total_frames = int(_REF_DURATION_S * 1000)  # 5.42s × 1000Hz = 5420 帧
    sample_count = max(1, 1 + max(0, total_frames - fixed_rate) // stride)

    for progress in _PROGRESS_STEPS:
        job.progress = progress
        session.commit()
        time.sleep(_PROGRESS_SLEEP)

    weld_id = record.weld_id
    samples: list[Sample] = []
    uploaded: list[str] = []
    try:
        for i in range(sample_count):
            sample = Sample(
                split_task_id=task.id,
                frame_no=i,
                meta={"weld_id": weld_id, "frame_no": i, "source": "split"},
            )
            session.add(sample)
            session.flush()  # 分配 id，object_keys 需用 sample.id
            sample.object_keys = [
                f"processed/{weld_id}/split/{sample.id}.jpg",
                f"processed/{weld_id}/split/{sample.id}.json",
            ]
            _write_sample_assets(sample, rules, task.task_format, uploaded)
            samples.append(sample)
    except Exception:
        _cleanup_uploaded_objects(uploaded)
        raise

    task.sample_count = sample_count
    session.add(task)

    result = {
        "sample_count": sample_count,
        "rules": rules,
        "task_format": task.task_format,
        "samples": [
            {
                "id": s.id,
                "frame_no": s.frame_no,
                "object_keys": s.object_keys,
                "annotation_task_id": s.annotation_task_id,
            }
            for s in samples[:_MAX_RESULT_SAMPLES]
        ],
    }
    mark_succeeded(session, job, result)
    return result



def _write_sample_assets(
    sample: Sample,
    rules: dict,
    task_format: str,
    uploaded: list[str],
) -> None:
    from app.storage import get_storage

    storage = get_storage()
    jpg_key, json_key = sample.object_keys
    jpg_bytes = b"\xff\xd8\xff\xd9"
    json_bytes = json.dumps(
        {
            "sample_id": sample.id,
            "frame_no": sample.frame_no,
            "task_format": task_format,
            "rules": rules,
            "meta": sample.meta,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    storage.upload_stream(jpg_key, io.BytesIO(jpg_bytes), len(jpg_bytes), "image/jpeg")
    uploaded.append(jpg_key)
    storage.upload_stream(json_key, io.BytesIO(json_bytes), len(json_bytes), "application/json")
    uploaded.append(json_key)



def _cleanup_uploaded_objects(uploaded: list[str]) -> None:
    from app.storage import get_storage

    storage = get_storage()
    for key in reversed(uploaded):
        try:
            storage.delete_object(key)
        except Exception:  # noqa: BLE001 - 清理失败只记日志，不覆盖原始异常
            logger.warning("清理切分产物失败: {}", key)
