"""系统设置·可选项字典（2026-09）：服务层 + `/settings/options` 端点。

服务层用内存 SQLite 直接调 `app.services.settings`（同 test_dataset_delete 风格）；
端点层沿用 test_files 的写法（StaticPool + 真实 app TestClient + 依赖覆盖）。

覆盖要点：
- 6 个选项组齐全、出厂默认值与字典化前的硬编码一致（machine/weld_method/dataset_task）；
- 新增重名 409、改名、停用/启用、上移下移整组重排；
- **删除语义**：未被引用 → 物理删（mode=deleted）；已被 `data_records.machine` 等引用
  → 软删为停用（mode=deactivated），历史数据不丢；
- 标注类别组落在既有 `label_categories` 表（不搬家），`GET /label-categories` 带 active，
  且 AI 预标注只从启用类别中抽样；
- 写操作仅管理员（403/40300），未登录读也 401。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import Annotation, AnnotationTask, DataRecord, LabelCategory, OptionItem, Sample, User
from app.services import annotation as annotation_svc
from app.services import settings as svc
from app.services.jobs import create_job


def _seed_annotations_session(session: Session, *, category: str, task_no: str):
    """建 job→annotation_task→sample→annotation 最小链路（annotation_tasks.job_id 非空）。

    返回 (task, sample) 供预标注用例继续使用。
    """
    job = create_job(session, type="annotation")
    task = AnnotationTask(job_id=job.id, source="manual", ls_status="legacy", name=task_no)
    session.add(task)
    session.flush()
    sample = Sample(annotation_task_id=task.id, frame_no=1, object_keys=[])
    session.add(sample)
    session.flush()
    session.add(Annotation(sample_id=sample.id, category=category, kind="box"))
    session.commit()
    return task, sample

client = TestClient(app)
OPTIONS_PATH = "/api/v1/settings/options"


def _group(session: Session, key: str) -> dict:
    """按 key 取分组——**不要用 `list_groups(session)[n]` 下标**：加一组就全体错位
    （2026-09-24 新增 material/thickness 时把 dataset_task 从 4 挪到 6，下标写法当场全红）。"""
    return next(group for group in svc.list_groups(session) if group["key"] == key)


# ── 服务层 ───────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as session:
        seed_all(session)
        yield session


def test_default_groups_match_former_hardcoded_options(session: Session) -> None:
    groups = {group["key"]: group for group in svc.list_groups(session)}
    assert list(groups) == list(svc.OPTION_GROUP_KEYS)
    values = lambda key: [item["value"] for item in groups[key]["items"] if item["active"]]  # noqa: E731
    assert values("machine") == ["Fronius CMT", "OTC FD-V8", "Panasonic YD-500"]
    assert values("weld_method") == ["MAG焊", "MIG焊", "TIG焊"]
    assert values("dataset_task") == ["目标检测", "语义分割", "多模态回归"]
    # 产品/项目信息无既有取值，出厂为空，由管理员在设置页维护。
    assert values("product") == []
    assert values("label_category") == ["焊瘤", "气孔", "未熔合", "咬边", "正常", "熔池"]
    # 板材材质 / 厚度（2026-09-24）：登记页这两个字段此前是纯文本。
    assert values("material")[0] == "Q235B" and "304 不锈钢" in values("material")
    # **厚度候选必须是纯数字**——提交时前端剥 `mm`、后端按数字校验 0.1–200，
    # 写成「6 mm」会被 422 挡下（用户点一下下拉就填进去的值，不能是过不了校验的值）。
    assert values("thickness") == ["3", "4", "5", "6", "8", "10", "12", "16", "20"]
    assert all(value.replace(".", "", 1).isdigit() for value in values("thickness"))


def test_create_rejects_duplicate_and_unknown_group(session: Session) -> None:
    with pytest.raises(svc.OptionConflict):
        svc.create_item(session, "machine", "Fronius CMT")
    with pytest.raises(svc.OptionGroupNotFound):
        svc.create_item(session, "not_a_group", "任意值")
    with pytest.raises(ValueError):
        svc.create_item(session, "machine", "   ")

    created = svc.create_item(session, "machine", "Kemppi Minarc")
    session.commit()
    assert created["value"] == "Kemppi Minarc"
    assert created["active"] is True
    # 新项追加到组末（sort_order 递增），下拉顺序稳定。
    assert svc.list_active_values(session, "machine")[-1] == "Kemppi Minarc"


def test_update_rename_and_deactivate_roundtrip(session: Session) -> None:
    item = svc.create_item(session, "weld_method", "激光焊")
    session.commit()

    renamed = svc.update_item(session, "weld_method", item["id"], value="激光焊（试点）")
    session.commit()
    assert renamed["value"] == "激光焊（试点）"

    off = svc.update_item(session, "weld_method", item["id"], active=False)
    session.commit()
    assert off["active"] is False
    assert "激光焊（试点）" not in svc.list_active_values(session, "weld_method")
    # 停用项仍在设置页可见（active=False），不会从管理界面消失。
    assert "激光焊（试点）" in [i["value"] for i in _group(session, "weld_method")["items"]]

    on = svc.update_item(session, "weld_method", item["id"], active=True)
    session.commit()
    assert on["active"] is True
    assert svc.list_active_values(session, "weld_method")[-1] == "激光焊（试点）"


def test_move_item_reorders_within_group(session: Session) -> None:
    machine = _group(session, "machine")["items"]
    first_id = machine[0]["id"]

    reordered = svc.move_item(session, "machine", first_id, "down")
    session.commit()
    assert [item["value"] for item in reordered][:2] == ["OTC FD-V8", "Fronius CMT"]
    # sort_order 整组重排为 10/20/30…，避免并列导致再次上移"看起来没生效"。
    assert [item["sort_order"] for item in reordered] == [10, 20, 30]

    # 再把刚被换下去的项上移一位 → 恢复出厂顺序。
    restored = svc.move_item(session, "machine", first_id, "up")
    session.commit()
    assert [item["value"] for item in restored][:2] == ["Fronius CMT", "OTC FD-V8"]
    # 边界（已在首位仍上移）静默不动作，顺序保持。
    assert [item["value"] for item in svc.move_item(session, "machine", first_id, "up")][:2] == ["Fronius CMT", "OTC FD-V8"]
    with pytest.raises(ValueError):
        svc.move_item(session, "machine", first_id, "diagonal")


def test_delete_unreferenced_is_physical(session: Session) -> None:
    item = svc.create_item(session, "source", "实验室 · 04号")
    session.commit()
    result = svc.delete_item(session, "source", item["id"])
    session.commit()
    assert result["mode"] == "deleted"
    assert "实验室 · 04号" not in svc.list_active_values(session, "source")


def test_delete_referenced_falls_back_to_deactivate(session: Session) -> None:
    """已被焊缝引用的焊机型号：删除 → 停用，历史登记仍保留原值。"""
    session.add(DataRecord(
        weld_id="WLD-OPT-001",
        registration_no="REG-OPT-001",
        source="产线相机 · 03号",
        machine="Panasonic YD-500",
        dataset_id=None,
    ))
    session.commit()

    machine = _group(session, "machine")["items"]
    target = next(item for item in machine if item["value"] == "Panasonic YD-500")
    result = svc.delete_item(session, "machine", target["id"])
    session.commit()

    assert result == {"mode": "deactivated", "value": "Panasonic YD-500", "references": 1}
    record = session.exec(select(DataRecord).where(DataRecord.weld_id == "WLD-OPT-001")).one()
    assert record.machine == "Panasonic YD-500"
    assert "Panasonic YD-500" not in svc.list_active_values(session, "machine")


def test_material_and_thickness_reference_checks(session: Session) -> None:
    """板材材质/厚度按 `data_records` 同名列统计引用。

    `reference_count` 是**白名单式**的，末尾 `raise OptionGroupNotFound`——新加一组却忘了
    加分支的话，这一组删除永远 40410（前端表现为"删不掉，也没说为什么"）。
    """
    session.add(DataRecord(
        weld_id="WLD-OPT-002", registration_no="REG-OPT-002",
        source="产线相机 · 03号", machine="Fronius CMT",
        material="Q235B", thickness="6", dataset_id=None,
    ))
    session.commit()

    referenced = next(i for i in _group(session, "material")["items"] if i["value"] == "Q235B")
    assert svc.delete_item(session, "material", referenced["id"])["mode"] == "deactivated"
    session.commit()
    row = session.get(OptionItem, referenced["id"])
    assert row is not None and row.active is False

    unused = next(i for i in _group(session, "thickness")["items"] if i["value"] == "12")
    assert svc.delete_item(session, "thickness", unused["id"])["mode"] == "deleted"
    session.commit()


def test_dataset_task_and_label_category_reference_checks(session: Session) -> None:
    """数据集任务类型与标注类别同样按引用情况决定软删/物理删。"""
    from app.services.datasets import create_dataset

    dataset = create_dataset(session, "任务类型引用测试集", "语义分割")
    session.commit()
    task_item = next(item for item in _group(session, "dataset_task")["items"] if item["value"] == "语义分割")
    assert svc.delete_item(session, "dataset_task", task_item["id"])["mode"] == "deactivated"
    session.commit()
    assert dataset.task == "语义分割"

    _seed_annotations_session(session, category="气孔", task_no="AN-OPT-001")

    pore = next(item for item in _group(session, "label_category")["items"] if item["value"] == "气孔")
    assert svc.delete_item(session, "label_category", pore["id"])["mode"] == "deactivated"
    session.commit()
    # 类别行走的仍是 label_categories（未搬家），停用只是 active=false。
    row = session.get(LabelCategory, pore["id"])
    assert row is not None and row.active is False


def test_pretag_only_samples_active_categories(session: Session) -> None:
    """停用类别不再进入 AI 预标注抽样（历史标注仍保留）。"""
    task, sample = _seed_annotations_session(session, category="焊瘤", task_no="AN-OPT-002")
    # 只留「气孔」一个启用类别，其余全部停用 → 预标注只能落「气孔」。
    keep = session.exec(select(LabelCategory).where(LabelCategory.name == "气孔")).one()
    for row in session.exec(select(LabelCategory)).all():
        row.active = row.id == keep.id
        session.add(row)
    session.commit()

    labels = annotation_svc.pretag_sample(session, task, sample)
    session.commit()
    assert labels
    assert {label.category for label in labels} == {"气孔"}
    # 接口仍返回停用类别（供历史标注解析），只是带 active=False。
    payload = {item["name"]: item["active"] for item in annotation_svc.list_label_categories(session)}
    assert payload["焊瘤"] is False and payload["气孔"] is True


# ── 端点层 ───────────────────────────────────────────────────────────


@pytest.fixture()
def db_session():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    with Session(eng) as session:
        seed_all(session)
        yield session
    eng.dispose()


@pytest.fixture()
def override_get_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def override_get_current_user():
    admin = User(
        id=1, username="lin_eng", password_hash="x", display_name="林工", role="admin"
    )

    def _override() -> User:
        return admin

    app.dependency_overrides[get_current_user] = _override
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_options_require_login(override_get_session) -> None:
    """未登录读字典 → 40100（不 override get_current_user）。"""
    resp = client.get(OPTIONS_PATH)
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_options_endpoint_returns_groups(override_get_session, override_get_current_user) -> None:
    resp = client.get(OPTIONS_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    groups = body["data"]["groups"]
    assert [group["key"] for group in groups] == list(svc.OPTION_GROUP_KEYS)
    assert groups[0]["items"][0]["value"] == "Fronius CMT"


def test_options_write_requires_admin(override_get_session) -> None:
    """字典是全局配置：非管理员写入 403（40300）。"""
    viewer = User(id=2, username="viewer", password_hash="x", display_name="访客", role="viewer")
    app.dependency_overrides[get_current_user] = lambda: viewer
    try:
        resp = client.post(f"{OPTIONS_PATH}/machine", json={"value": "非法写入型号"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_options_create_update_delete_via_api(override_get_session, override_get_current_user) -> None:
    created = client.post(f"{OPTIONS_PATH}/machine", json={"value": "Kemppi Minarc"})
    assert created.status_code == 200
    item = created.json()["data"]["item"]
    assert item["value"] == "Kemppi Minarc"
    assert created.json()["data"]["group"]["items"][-1]["id"] == item["id"]

    duplicate = client.post(f"{OPTIONS_PATH}/machine", json={"value": "Kemppi Minarc"})
    assert duplicate.status_code == 409 and duplicate.json()["code"] == 40900

    renamed = client.patch(f"{OPTIONS_PATH}/machine/{item['id']}", json={"value": "Kemppi X7"})
    assert renamed.status_code == 200 and renamed.json()["data"]["item"]["value"] == "Kemppi X7"

    moved = client.post(f"{OPTIONS_PATH}/machine/{item['id']}/move", json={"direction": "up"})
    assert moved.status_code == 200
    # 新项原在组末，上移一位 → 倒数第二，原倒数第二（Panasonic YD-500）落到末尾。
    assert [i["value"] for i in moved.json()["data"]["items"]][-2:] == ["Kemppi X7", "Panasonic YD-500"]

    deleted = client.delete(f"{OPTIONS_PATH}/machine/{item['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["mode"] == "deleted"

    missing = client.patch(f"{OPTIONS_PATH}/machine/{item['id']}", json={"value": "不存在"})
    assert missing.status_code == 404 and missing.json()["code"] == 40411

    unknown_group = client.post(f"{OPTIONS_PATH}/nope", json={"value": "x"})
    assert unknown_group.status_code == 404 and unknown_group.json()["code"] == 40410
