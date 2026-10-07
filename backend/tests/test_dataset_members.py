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

from app.models.analysis import Annotation, AnnotationTask, Sample, SplitTask
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services.datasets import (
    _assign_splits,
    _assign_within_weld,
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
    """判重按产物：3 条无产物各自唯一，2 条产物完全相同的**两条都计**重复 → 2/5。

    口径（T2.3 起）：同一组重复切片里每条都计入 `repeat` 失败集合——产物相同的两条无法
    判断哪条是"真的"，两条都不算有效切片；这也让 `repeat_rate` 与 `deductions.repeat.affected`
    一致（affected=2 ↔ rate=0.4×5）。旧公式 `total - len(去重键)` 只计多余的那几条（当时是 0.2），
    与 `affected` 对不上。
    """
    with Session(engine) as session:
        # 任务用「时序分类」：REQUIRED_BY_TASK 里没有它 → 不触发 missing_field，
        # 这样这条用例只考察判重口径（否则无产物样本还会因缺维度命中第三项原因）。
        dataset, record, _version = _dataset_with_record(session, "判重口径", "时序分类")
        samples: list[Sample] = []
        for _ in range(3):
            samples.append(
                Sample(
                    frame_no=None,
                    meta={"record_id": record.id, "weld_id": record.weld_id},
                )
            )
        for _ in range(2):
            samples.append(
                Sample(
                    frame_no=5,
                    object_keys=["processed/x/same.csv"],
                    meta={"record_id": record.id, "weld_id": record.weld_id},
                )
            )
        session.add_all(samples)
        session.flush()
        # 全部标注上，隔离出"重复"这一项原因
        for sample in samples:
            session.add(Annotation(sample_id=sample.id, category="气孔"))
        session.commit()

        record_ids = {sample.id: _sample_record_id(session, sample) for sample in samples}
        quality = _compute_quality(session, dataset, samples, record_ids)

        assert quality["repeat_rate"] == 0.4
        assert quality["deductions"]["repeat"]["affected"] == 2
        assert quality["empty_label_rate"] == 0.0
        # 3 条无产物各自唯一 → 3/5 有效
        assert quality["effective_ratio"] == 0.6

# ── R3：时序维度必须由**真实导入的通道**驱动 ─────────────────────────


def _ingest(
    session: Session, version_id: int, column_map: dict, status: str = "succeeded"
) -> None:
    from app.models.analysis import SignalIngest

    job = _job(session, "signal_ingest", status)
    session.add(
        SignalIngest(
            job_id=job.id,
            version_id=version_id,
            source_object_key=f"raw/{uuid4().hex[:8]}.csv",
            status=status,
            column_map=column_map,
        )
    )
    session.flush()


def test_time_series_dimensions_come_from_imported_channels(engine):
    """同一份 `.csv`，通道不同 → 维度结论不同。

    改造前 `_dimension_availability_from_samples` 看见 `.csv` 扩展名（甚至文件名里有 `current`）
    就把 电流/电压/气流/送丝/焊接速度 全部点亮——缺列的 CSV 也能"字段完备"，属于假通过。
    """
    from app.services.datasets import _dimension_availability_from_samples

    with Session(engine) as session:
        _, record, version = _dataset_with_record(session, "只有电流列的数据集")
        # 只有电流与时间列：没有电压 / 气流 / 送丝 / 焊接速度
        _ingest(session, version.id, {"time": "time", "cur": "Current"})
        sample = Sample(
            object_keys=["processed/x/1/000001.csv"],
            meta={"source": "dataset_record", "record_id": record.id},
        )
        session.add(sample)
        session.flush()

        dims = _dimension_availability_from_samples(session, [sample])

        assert dims["Current"] is True
        assert dims["Voltage"] is False, "缺电压列的 CSV 不得被判成电压已具备"
        assert dims["GasSpeed"] is False
        assert dims["送丝速度"] is False
        assert dims["焊接速度"] is False

        # 补上标准多模态通道后逐项点亮
        _ingest(
            session,
            version.id,
            {"time": "time", "cur": "Current", "vol": "Voltage", "gas": "GasSpeed", "wir": "WireFeedSpeed", "weld_speed": "WeldingSpeed"},
        )
        dims = _dimension_availability_from_samples(session, [sample])
        assert all(dims[name] for name in ("Current", "Voltage", "GasSpeed", "送丝速度", "焊接速度"))


def test_failed_or_missing_import_does_not_light_up_time_series_dimensions(engine):
    """导入失败 / 还在排队 / 根本没有 CSV：都不算"已具备"（只认 succeeded 的 column_map）。"""
    from app.services.datasets import _dimension_availability_from_samples

    with Session(engine) as session:
        _, record, version = _dataset_with_record(session, "导入失败的数据集")
        _ingest(session, version.id, {"time": "time", "cur": "Current"}, status="failed")
        _ingest(session, version.id, {"time": "time", "cur": "Current"}, status="running")
        sample = Sample(object_keys=["raw/x.csv"], meta={"source": "dataset_record", "record_id": record.id})
        session.add(sample)
        session.flush()

        dims = _dimension_availability_from_samples(session, [sample])
        assert dims["Current"] is False
        assert dims["Voltage"] is False


def test_time_series_dimensions_survive_analysis_versions(engine):
    """分析产物版本会把 `latest_version_id` 指走且自身没有导入行——按"当前版本"查通道会看丢。

    所以通道按**登记数据的全部版本**取：CSV 挂在 v1.0，v1.1 是「时间对齐」产物，仍要认得电流电压。
    """
    from app.services.datasets import _dimension_availability_from_samples

    with Session(engine) as session:
        _, record, version = _dataset_with_record(session, "有分析版本的数据集")
        _ingest(session, version.id, {"time": "time", "cur": "Current", "vol": "Voltage"})
        aligned = DataVersion(
            record_id=record.id, version_no="v1.1", action="时间对齐", object_keys=[]
        )
        session.add(aligned)
        session.flush()
        record.latest_version_id = aligned.id
        sample = Sample(
            object_keys=["processed/x/1/000001.csv"],
            meta={"source": "dataset_record", "record_id": record.id},
        )
        session.add(sample)
        session.flush()

        dims = _dimension_availability_from_samples(session, [sample])
        assert dims["Current"] and dims["Voltage"]


# ── 划分规则（2026-10：单焊缝按时间连续块） ──────────────────────────
#
# 这两条规则在真实构建里靠 E2E 覆盖（见 `test_sample_features_e2e.py`），但边界
# （1 个样本 / 2 条焊缝 / "连续块不许打散"）在端到端里构造代价高，故在这里直接钉住。


def _fake_samples(count: int) -> list[Sample]:
    """`start_time` 递增的假切片（顺序即时间顺序，用来断言"连续块"）。

    **显式给 id**：`_assign_within_weld` 用 `sample.id` 作字典键，未落库的 Sample
    其 `id` 是 None，全都会塌成同一个键。
    """
    return [
        Sample(id=index + 1, split_task_id=1, frame_no=index + 1, start_time=index * 2.0,
               end_time=index * 2.0 + 2.0, object_keys=[])
        for index in range(count)
    ]


def test_assign_splits_two_welds_gives_a_validation_split():
    """2 条焊缝：train / **val**（原先给的是 `test`，而训练准入查的是 `val`——
    那种版本其实训不了；两个焊缝足以做跨焊缝验证，给 val 才有意义）。

    组序经 seed=42 打乱，故只断言两个分片的**取值集合**。
    """
    assignments = _assign_splits(["w1", "w2"])
    assert set(assignments.values()) == {"train", "val"}, assignments
    assert len(assignments) == 2


def test_assign_splits_single_weld_defers_to_within_weld():
    """1 条焊缝：**返回空**，由调用方走 `_assign_within_weld`（不再"整条丢 train"）。"""
    assert _assign_splits(["w1"]) == {}


def test_assign_splits_three_or_more_has_both_val_and_test():
    for count in (3, 5, 40):
        assignments = _assign_splits([f"w{i}" for i in range(count)])
        splits = set(assignments.values())
        assert "train" in splits and "val" in splits and "test" in splits, (count, assignments)
        # 同一个焊缝绝不跨分片
        assert len(assignments) == count
    # 确定性可复现
    assert _assign_splits([f"w{i}" for i in range(10)]) == _assign_splits([f"w{i}" for i in range(10)])


def test_within_weld_split_is_contiguous_in_time_and_keeps_val_non_empty():
    """单焊缝内划分：训练准入要 val 非空，所以样本够时必须切出 val（和 test）。"""
    samples = _fake_samples(9)
    assignment = _assign_within_weld(samples)
    counts = {name: list(assignment.values()).count(name) for name in ("train", "val", "test")}
    assert counts == {"train": 7, "val": 1, "test": 1}, counts
    assert all(sample.id in assignment for sample in samples), "每个样本都要有归属"

    # **连续块**：按时间排序后每个分片的下标是连续区间（不许打散——相邻窗口高度相关，
    # 打散等于把验证窗口的邻居放进训练集）
    ordered = sorted(samples, key=lambda s: s.start_time)
    labels = [assignment[s.id] for s in ordered]
    assert labels == sorted(labels, key=lambda name: {"train": 0, "val": 1, "test": 2}[name]), labels


def test_within_weld_split_edge_cases():
    """样本过少时优先保 train 与 val 各一个（丢掉 test）——否则准入必然拒。"""
    assert {list(_assign_within_weld(_fake_samples(2)).values()).count(name) for name in ("train", "val")} == {1}
    assert set(_assign_within_weld(_fake_samples(2)).values()) == {"train", "val"}
    # 只有 1 个样本：只能给 train，val=0 → 如实让准入拒绝（不是这里硬凑）
    only = _fake_samples(1)
    assert _assign_within_weld(only) == {only[0].id: "train"}
    assert _assign_within_weld([]) == {}
    # 3 个样本也必须有 val
    assert "val" in set(_assign_within_weld(_fake_samples(3)).values())
