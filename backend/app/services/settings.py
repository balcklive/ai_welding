"""系统设置·可选项字典（服务层）。

职责：把「录入时可选项」统一成 **选项组（group）+ 选项项（item）** 两层模型，
对上层（`api/v1/settings.py` 与前端设置页）暴露同一套增删改查；对下层屏蔽
「两类存储」的差异：

1. `option_items`（新表）——承载 machine / weld_method / source / product / dataset_task；
2. `label_categories`（既有表，LS 集成与标注校验依赖）——承载 label_category，
   仅在迁移 0015 补 `active` + `sort_order`，不搬家、不改存储语义。

`defect_category`（分段样本段级标注的主缺陷词表，迁移 0020）**落在 `option_items` 上**
——同一套"分组 + 软删 + 排序"设施，只是分组语义不同，故存储分支与 1 相同，
不新增第三张表；唯一的差异在 `reference_count`（按 id 引用而非字符串列）。

设计规则（与用户确认的范围一致）：
- **停用即删减**：`DELETE` 时若该值已被业务数据引用（`data_records.machine` 等），
  执行软删（`active=False`）——历史数据仍按原字符串展示，录入候选里不再出现；
  未被引用的项直接物理删除。返回值 `mode` 区分 `deleted` / `deactivated`。
- **改名只影响后续录入**：历史 `data_records` / `datasets` / `annotations` 里存的是
  字符串快照，不做回填（避免静默改写历史台账）。
- **分组键固定**：见 `OPTION_GROUPS`；未知 group_key 抛 `OptionGroupNotFound`。

坑/边界：
- 本模块**不 commit**（与 `services/welds.py`、`services/datasets.py` 一致），由路由统一提交。
- `active` 在 SQLite/MySQL 上都是布尔列，读出后统一 `bool(...)` 归一（MySQL 可能回 0/1）。
- `sort_order` 允许并列；列表按 `(sort_order, id)` 稳定排序，`move_item` 会整组重排，
  避免并列导致"上移/下移"看起来没生效。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.models.analysis import Annotation, LabelCategory, SampleAnnotation
from app.models.data import DataRecord
from app.models.datasets import Dataset
from app.models.settings import OptionItem

#: label_categories 的分组键（存储表与其它组不同）。
LABEL_CATEGORY_GROUP = "label_category"

#: 分段样本缺陷词表的分组键。落在 `option_items` 上（存储与 machine/weld_method 等相同），
#: 只是**语义上**与「标注缺陷类别」分属两套词表：后者是模型口径（LS 集成与
#: `POST …/labels` 校验依赖），前者是段级分类的主缺陷类别。`sample_annotations` 通过
#: `defect_category_id` 引用本组的 `option_items.id`（稳定 ID），并存名称快照。
DEFECT_CATEGORY_GROUP = "defect_category"

#: 选项组定义（顺序即前端设置页展示顺序）。
#: `color` = 该项是否支持颜色（仅标注类别需要）；`free_text` = 录入页是否允许手工填写
#: 非候选值——**默认项不足时能自定义输入**（S2，2026-09-15 起 machine/weld_method 也放开），
#: 这类组的下拉只做候选提示，不是强约束。
OPTION_GROUPS: tuple[dict, ...] = (
    {
        "key": "machine",
        "label": "数据厂家 / 焊机型号",
        "description": "数据登记页「焊机型号」下拉的可选项；录入时仍可手工填写未列出的型号。数据总览的厂商比重与词云按该值首个词统计，新值建议事后补进这里，避免同一厂家多种写法。",
        "color": False,
        "free_text": True,
    },
    {
        "key": "weld_method",
        "label": "焊接方法",
        "description": "数据登记页「焊接方法」下拉的可选项；录入时仍可手工填写未列出的方法。数据总览只对这里列出的方法映射熔滴过渡类型，其它值统一计入「未分类」。",
        "color": False,
        "free_text": True,
    },
    {
        "key": "source",
        "label": "数据来源",
        "description": "数据登记页「数据来源」的候选值；录入时仍可手工填写未列出的来源。",
        "color": False,
        "free_text": True,
    },
    {
        "key": "product",
        "label": "产品 / 项目信息",
        "description": "数据登记页「关联产品信息」的候选值（产品型号、零件编号或项目名）；录入时仍可手工填写。",
        "color": False,
        "free_text": True,
    },
    {
        "key": "material",
        "label": "板材材质",
        "description": "数据登记页「板材材质」下拉的可选项；录入时仍可手工填写未列出的材质。出厂值为常见焊接板材牌号，按实际产线替换即可。",
        "color": False,
        "free_text": True,
    },
    {
        "key": "thickness",
        "label": "板材厚度",
        "description": "数据登记页「板材厚度」下拉的可选项，单位 mm；录入时仍可手工填写未列出的厚度（0.1–200）。候选值只作提示——提交的是纯数字，加「mm」会进不了量程。",
        "color": False,
        "free_text": True,
    },
    {
        "key": "dataset_task",
        "label": "数据集任务类型",
        "description": "新建数据集时可选择的任务类型；决定该数据集的必需输入维度与模型适配检查项。",
        "color": False,
        "free_text": False,
    },
    {
        "key": "label_category",
        "label": "标注缺陷类别",
        "description": "数据标注页的标签类别；停用后不再出现在标签调色板与 AI 预标注中，历史标注仍可正常显示。",
        "color": True,
        "free_text": False,
    },
    {
        "key": DEFECT_CATEGORY_GROUP,
        "label": "分段样本缺陷词表",
        "description": "分段样本标注（段级分类）选「缺陷」时的主缺陷类别；停用后新建标注不可选、历史标注仍按当时名称显示。与「标注缺陷类别」是两套词表。",
        "color": False,
        "free_text": False,
    },
)

#: 合法分组键（供路由/测试直接断言）。
OPTION_GROUP_KEYS: tuple[str, ...] = tuple(group["key"] for group in OPTION_GROUPS)


class OptionGroupNotFound(ValueError):
    """未知选项分组键。"""


class OptionItemNotFound(ValueError):
    """选项项不存在（含 id 不属于该分组）。"""


class OptionConflict(ValueError):
    """同组内选项值重复。"""


def get_group(key: str) -> dict:
    """按 key 取分组定义；未知 key 抛 `OptionGroupNotFound`。"""
    for group in OPTION_GROUPS:
        if group["key"] == key:
            return group
    raise OptionGroupNotFound(f"未知的选项分组：{key}")


def _serialize(item) -> dict:
    """统一序列化两类存储行为同一形状（id/value/color/active/sort_order）。"""
    if isinstance(item, LabelCategory):
        return {
            "id": item.id,
            "value": item.name,
            "color": item.color,
            "active": bool(item.active),
            "sort_order": int(item.sort_order or 0),
        }
    return {
        "id": item.id,
        "value": item.value,
        "color": None,
        "active": bool(item.active),
        "sort_order": int(item.sort_order or 0),
    }


def _query(session: Session, group_key: str) -> list:
    """按分组读取原始行（含停用项，供设置页展示），稳定排序 `(sort_order, id)`。"""
    group = get_group(group_key)
    if group_key == LABEL_CATEGORY_GROUP:
        return list(
            session.exec(
                select(LabelCategory).order_by(LabelCategory.sort_order, LabelCategory.id)
            ).all()
        )
    return list(
        session.exec(
            select(OptionItem)
            .where(OptionItem.group_key == group_key)
            .order_by(OptionItem.sort_order, OptionItem.id)
        ).all()
    )


def _find(session: Session, group_key: str, item_id: int):
    """按 (分组, id) 定位选项行；不存在或不属于该分组抛 `OptionItemNotFound`。"""
    if group_key == LABEL_CATEGORY_GROUP:
        row = session.get(LabelCategory, item_id)
    else:
        row = session.get(OptionItem, item_id)
        if row is not None and row.group_key != group_key:
            row = None
    if row is None:
        raise OptionItemNotFound(f"选项不存在：{group_key}#{item_id}")
    return row


def _value_of(row) -> str:
    return row.name if isinstance(row, LabelCategory) else row.value


def _set_value(row, value: str) -> None:
    if isinstance(row, LabelCategory):
        row.name = value
    else:
        row.value = value


def _duplicate_exists(session: Session, group_key: str, value: str, exclude_id: int | None) -> bool:
    """同组内是否已存在同名选项（大小写/空白敏感，与业务字符串列一致）。"""
    for row in _query(session, group_key):
        if row.id == exclude_id:
            continue
        if _value_of(row) == value:
            return True
    return False


def _flush_or_conflict(session: Session, value: str) -> None:
    """flush 并兜住唯一约束竞态：两个管理员同时新增同名项时，预检查可能都通过，
    最终由 `(group_key, value)` / `label_categories.name` 的唯一键拦下——
    统一转成 `OptionConflict`（409）而不是 500。回滚由调用方路由随请求结束处理。
    """
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise OptionConflict(f"该分组已存在选项：{value}") from exc


def reference_count(session: Session, group_key: str, row) -> int:
    """该选项在业务表中的引用条数（决定删除走软删还是物理删）。

    取**行对象**而不是值：多数分组按字符串列引用（`data_records.machine` 等），
    但 `defect_category` 是按**外键 id** 引用（`sample_annotations.defect_category_id`）
    ——只拿值查不出引用，改名后更查不出。行对象两种都够用。
    """
    value = _value_of(row)

    def _count(column) -> int:
        return int(session.exec(select(func.count(column)).where(column == value)).one())

    def _count_id(column) -> int:
        return int(session.exec(select(func.count(column)).where(column == row.id)).one())

    if group_key == "machine":
        return _count(DataRecord.machine)
    if group_key == "weld_method":
        return _count(DataRecord.weld_method)
    if group_key == "source":
        return _count(DataRecord.source)
    if group_key == "product":
        return _count(DataRecord.product)
    if group_key == "material":
        return _count(DataRecord.material)
    if group_key == "thickness":
        return _count(DataRecord.thickness)
    if group_key == "dataset_task":
        return _count(Dataset.task)
    if group_key == LABEL_CATEGORY_GROUP:
        return _count(Annotation.category)
    if group_key == DEFECT_CATEGORY_GROUP:
        return _count_id(SampleAnnotation.defect_category_id)
    raise OptionGroupNotFound(f"未知的选项分组：{group_key}")


def list_groups(session: Session) -> list[dict]:
    """全部选项组 + 各自选项（含停用项，`active=False` 由前端标为「已停用」）。"""
    groups: list[dict] = []
    for group in OPTION_GROUPS:
        items = [_serialize(row) for row in _query(session, group["key"])]
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "description": group["description"],
                "color": group["color"],
                "free_text": group["free_text"],
                "items": items,
            }
        )
    return groups


def list_active_values(session: Session, group_key: str) -> list[str]:
    """某分组下启用中的选项值（录入页下拉/候选直接消费）。"""
    return [
        _value_of(row) for row in _query(session, group_key) if bool(row.active)
    ]


def create_item(
    session: Session, group_key: str, value: str, color: str | None = None
) -> dict:
    """新增选项：同组内重名 → `OptionConflict`；sort_order 追加到组末。"""
    get_group(group_key)
    value = value.strip()
    if not value:
        raise ValueError("选项内容不能为空")
    if _duplicate_exists(session, group_key, value, exclude_id=None):
        raise OptionConflict(f"该分组已存在选项：{value}")

    rows = _query(session, group_key)
    next_order = (max((int(r.sort_order or 0) for r in rows), default=0)) + 10
    now = datetime.now(timezone.utc)
    if group_key == LABEL_CATEGORY_GROUP:
        row = LabelCategory(
            name=value, color=color, sort_order=next_order, active=True
        )
    else:
        row = OptionItem(
            group_key=group_key,
            value=value,
            sort_order=next_order,
            active=True,
            created_at=now,
            updated_at=now,
        )
    session.add(row)
    _flush_or_conflict(session, value)
    return _serialize(row)


def update_item(
    session: Session,
    group_key: str,
    item_id: int,
    *,
    value: str | None = None,
    color: str | None = None,
    active: bool | None = None,
) -> dict:
    """改名 / 改颜色 / 停用-启用。空值字段跳过（PATCH 语义）。"""
    get_group(group_key)
    row = _find(session, group_key, item_id)

    if value is not None:
        value = value.strip()
        if not value:
            raise ValueError("选项内容不能为空")
        if _duplicate_exists(session, group_key, value, exclude_id=item_id):
            raise OptionConflict(f"该分组已存在选项：{value}")
        _set_value(row, value)
    if color is not None and group_key == LABEL_CATEGORY_GROUP:
        row.color = color
    if active is not None:
        row.active = bool(active)
    if not isinstance(row, LabelCategory):
        row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    _flush_or_conflict(session, _value_of(row))
    return _serialize(row)


def move_item(session: Session, group_key: str, item_id: int, direction: str) -> list[dict]:
    """上移/下移一位：与相邻项交换后整组按 10 递增重排 sort_order。

    已到边界（无相邻项）时静默不动作；返回该分组重排后的完整列表。
    """
    get_group(group_key)
    if direction not in {"up", "down"}:
        raise ValueError("direction 只能是 up / down")
    row = _find(session, group_key, item_id)
    rows = _query(session, group_key)
    index = next((i for i, item in enumerate(rows) if item.id == row.id), None)
    if index is None:
        raise OptionItemNotFound(f"选项不存在：{group_key}#{item_id}")
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(rows):
        rows[index], rows[target] = rows[target], rows[index]
        for position, item in enumerate(rows, start=1):
            item.sort_order = position * 10
            session.add(item)
        session.flush()
    return [_serialize(item) for item in rows]


def delete_item(session: Session, group_key: str, item_id: int) -> dict:
    """删除选项：有业务引用 → 软删（停用）；无引用 → 物理删除。

    返回 `{"mode": "deleted" | "deactivated", "value": ..., "references": n}`。
    """
    get_group(group_key)
    row = _find(session, group_key, item_id)
    value = _value_of(row)
    references = reference_count(session, group_key, row)
    if references > 0:
        row.active = False
        if not isinstance(row, LabelCategory):
            row.updated_at = datetime.now(timezone.utc)
        session.add(row)
        session.flush()
        return {"mode": "deactivated", "value": value, "references": references}
    session.delete(row)
    session.flush()
    return {"mode": "deleted", "value": value, "references": 0}
