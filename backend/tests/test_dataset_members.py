"""数据集成员来源与判重（T11，2026-09-14）。

回归的线上事故：`_samples_for_dataset_records` 把数据集下**全部** Sample 都收进版本，
于是 7 个标注锚点样本混进成员，再被 `(record_id, frame_no)` 判重规则判成互相重复，
把 `repeat_rate` 假报成 0.75。这里逐条钉住修复后的四条规则：

1. 标注锚点样本不得成为成员；
2. 每条登记数据二选一（最近一次**成功**分段任务的切片 / 基础样本），不混合；
3. 分段任务必须成功才作数，旧任务的切片算历史切片、不进版本；
4. 判重按产物 `(record_id, object_keys)`，且**无产物的样本视为唯一**。
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from app.models.analysis import AnnotationTask, Sample, SplitTask
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services.datasets import (
    _compute_quality,
    _is_annotation_anchor,
    _sample_record_id,
    _samples_for_dataset_records,
    create_dataset,
)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _job(session: Session, job_type: str, status: str = "succeeded") -> Job:
    job = Job(job_uid=f"job_{uuid4().hex[:8]}", type=job_type, status=status)
    session.add(job)
    session.flush()
    return job


def _split_task(
    session: Session, version_id: int, status: str = "succeeded"
) -> SplitTask:
    job = _job(session, "split", status)
    task = SplitTask(
        job_id=job.id, version_id=version_id, rules={"fixed_rate": 10}, task_format="时序分类"
    )
    session.add(task)
    session.flush()
    return task


def _slice(session: Session, task: SplitTask, index: int) -> Sample:
    """切片：注意**不写** meta.record_id —— 真实数据靠 split_task→version→record 反查归属。"""
    sample = Sample(
        split_task_id=task.id,
        frame_no=index,
        object_keys=[f"processed/x/{task.id}/{index:06d}.csv"],
        meta={"sample_index": index, "source_version_id": task.version_id},
    )
    session.add(sample)
    return sample


def _dataset_with_record(session: Session, name: str, task: str = "目标检测"):
    dataset = create_dataset(session, name, task)
    record = DataRecord(
        weld_id=f"WLD-{uuid4().hex[:8]}",
        registration_no=f"REG-{uuid4().hex[:8]}",
        source="test",
        dataset_id=dataset.id,
    )
    session.add(record)
    session.flush()
    version = DataVersion(
        record_id=record.id, version_no="v1.0", action="原始数据", object_keys=["raw/a.mp4"]
    )
    session.add(version)
    session.flush()
    record.latest_version_id = version.id
    return dataset, record, version


def test_is_annotation_anchor_rules():
    assert _is_annotation_anchor(Sample(meta={"source": "video-anchor"}))
    assert _is_annotation_anchor(Sample(meta={"source": "signal-anchor"}))
    # 标注任务导入的锚点/帧样本：没有切分归属，但有标注任务归属
    assert _is_annotation_anchor(Sample(annotation_task_id=1))
    # 切分产物与基础样本都不是锚点
    assert not _is_annotation_anchor(Sample(split_task_id=1, meta={"sample_index": 1}))
    assert not _is_annotation_anchor(Sample(meta={"source": "dataset_record"}))


def test_annotation_anchors_are_excluded_and_do_not_fake_repeat_rate(engine):
    """线上事故原样复现：7 个锚点样本 + 无分段 → 成员只剩 1 条基础样本，重复率 0。"""
    with Session(engine) as session:
        dataset, record, version = _dataset_with_record(session, "带锚点的数据集")
        anno_task = AnnotationTask(
            job_id=_job(session, "annotation").id, source="signal", name="AN-1"
        )
        session.add(anno_task)
        session.flush()
        for _ in range(7):
            session.add(
                Sample(
                    annotation_task_id=anno_task.id,
                    meta={
                        "mode": "signal",
                        "source": "signal-anchor",
                        "weld_id": record.weld_id,
                        "version_id": version.id,
                    },
                )
            )
        session.commit()

        members = _samples_for_dataset_records(session, dataset)

        assert len(members) == 1
        assert members[0].meta["source"] == "dataset_record"
        assert members[0].object_keys == ["raw/a.mp4"]

        record_ids = {member.id: _sample_record_id(session, member) for member in members}
        quality = _compute_quality(session, dataset, members, record_ids)
        assert quality["repeat_rate"] == 0.0


def test_base_sample_is_reused_instead_of_piling_up(engine):
    """基础样本按登记数据复用，不在每次构建时新建一条。"""
    with Session(engine) as session:
        dataset, _record, _version = _dataset_with_record(session, "复用基础样本")
        first = _samples_for_dataset_records(session, dataset)
        session.commit()
        second = _samples_for_dataset_records(session, dataset)

        assert [sample.id for sample in second] == [sample.id for sample in first]
        assert session.exec(select(Sample)).all().__len__() == 1


def test_only_latest_succeeded_split_slices_are_members(engine):
    """旧任务与失败任务的切片都不得进版本，只有最近一次成功任务的切片能进。"""
    with Session(engine) as session:
        dataset, _record, version = _dataset_with_record(session, "两次分段", "时序分类")
        old_task = _split_task(session, version.id)
        for index in (1, 2, 3):
            _slice(session, old_task, index)
        failed_task = _split_task(session, version.id, status="failed")
        _slice(session, failed_task, 1)
        new_task = _split_task(session, version.id)
        for index in (1, 2):
            _slice(session, new_task, index)
        session.commit()

        members = _samples_for_dataset_records(session, dataset)

        assert len(members) == 2
        assert {member.split_task_id for member in members} == {new_task.id}
        # 有成功分段时不得再混进基础样本
        assert all(member.split_task_id is not None for member in members)


def test_repeat_rate_counts_by_object_keys_and_ignores_empty_ones(engine):
    """判重按产物：3 条无产物各自唯一，2 条产物完全相同算 1 条重复 → 1/5。"""
    with Session(engine) as session:
        dataset, record, _version = _dataset_with_record(session, "判重口径")
        for _ in range(3):
            session.add(
                Sample(
                    frame_no=None,
                    meta={"record_id": record.id, "weld_id": record.weld_id},
                )
            )
        for _ in range(2):
            session.add(
                Sample(
                    frame_no=5,
                    object_keys=["processed/x/same.csv"],
                    meta={"record_id": record.id, "weld_id": record.weld_id},
                )
            )
        session.commit()

        samples = list(session.exec(select(Sample)).all())
        record_ids = {sample.id: _sample_record_id(session, sample) for sample in samples}
        quality = _compute_quality(session, dataset, samples, record_ids)

        assert quality["repeat_rate"] == 0.2
