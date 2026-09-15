"""总览「过渡类型」映射回归（S2，2026-09-15）。

背景：登记页从 2026-09-15 起允许焊机型号/焊接方法**自定义输入**（候选由系统设置字典维护，
但不再是强约束）。`get_distributions` 原来对映射表外的焊法兜底成「脉冲过渡」，等于把现场
新方法**静默算成脉冲过渡**——一个看起来正常、实际错误的结论。改成统一计入「未分类」。

覆盖：已知焊法按映射归位；映射表外的自定义焊法进「未分类」且**不污染**「脉冲过渡」；
自定义焊法仍出现在 welding_types（原始值不丢）。
"""

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.models.data import DataRecord
from app.services import dashboard as svc


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _record(session: Session, *, no: int, weld_method: str) -> DataRecord:
    record = DataRecord(
        weld_id=f"WLD-TEST-{no:04d}",
        registration_no=f"REG-TEST-{no:04d}",
        source="测试产线",
        weld_method=weld_method,
        quality="待复核",
    )
    session.add(record)
    return record


def _transition(session: Session) -> dict[str, int]:
    dist = svc.get_distributions(session)
    return {item["name"]: item["value"] for item in dist["transition_types"]}


def test_known_weld_methods_still_map_to_their_transition(session: Session):
    _record(session, no=1, weld_method="MAG焊")
    _record(session, no=2, weld_method="MAG焊")
    _record(session, no=3, weld_method="埋弧焊")
    session.commit()

    assert _transition(session) == {"短路过渡": 2, "脉冲过渡": 1}


def test_unknown_weld_method_goes_to_unclassified_not_pulse(session: Session):
    """自定义焊法必须进「未分类」——旧实现的兜底是「脉冲过渡」，会给出错误结论。"""
    _record(session, no=1, weld_method="埋弧焊")
    _record(session, no=2, weld_method="激光-电弧复合焊")  # 映射表外（现场自定义输入）
    _record(session, no=3, weld_method="激光-电弧复合焊")
    session.commit()

    transition = _transition(session)
    assert transition["脉冲过渡"] == 1, "自定义焊法不得被算进脉冲过渡"
    assert transition[svc.UNKNOWN_TRANSITION] == 2
    # 原始值不丢：焊接类型分布里仍是自定义焊法的原文。
    welding = {item["name"]: item["value"] for item in svc.get_distributions(session)["welding_types"]}
    assert welding["激光-电弧复合焊"] == 2


def test_mapping_table_values_are_covered_by_the_chart_vocabulary(session: Session):
    """映射目标词表去重后仍是图例能表达的数量（防有人往映射表里塞新词而不改前端）。"""
    targets = set(svc.TRANSITION_BY_WELD_METHOD.values()) | {svc.UNKNOWN_TRANSITION}
    assert targets <= {"短路过渡", "射流过渡", "混合过渡", "脉冲过渡", "CMT", "未分类"}
