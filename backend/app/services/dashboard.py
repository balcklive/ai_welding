"""Dashboard 总览服务（Task 8）：四个总览端点的聚合查询。

- `get_stats`：统计卡——数据总量 / 厂商总量 / 单条焊缝最大容量 / 已标注样本 + 完成度。
- `get_attributes`：属性面板——焊机种类 / 缺陷种类 / 多模态种类 / 采集频率档位。
- `get_distributions`：分布图——厂商比重 / 过渡类型 / 焊接类型 / 缺陷分布 / 厂商词云。
- `get_projects`：数据项目卡片（从 `datasets` 派生）。

形状对齐 `src/App.tsx` Overview 消费的常量（manufacturers / transitionTypes /
weldingTypes / defectTypes / wordCloud / projects），字段名与前端一致；tone/颜色由
前端自己映射，后端不输出。缺陷分布用**统计口径**词表（§3.2 说明，含未焊透/焊穿/
夹渣等更细类型），与标注用"标签类别"（焊瘤/气孔/未熔合/咬边/正常）是两套词表，勿混用。

坑：`session.exec(select(单列/聚合函数))` 是 `SelectOfScalar`，返回的是**标量**结果
（`.one()`/`.all()` 直接给值，不是 Row）；只有 `select(多列)`/`select(模型)` 才返回 Row。
聚合助手已按此约定取值，勿再套 `[0]`。另：计数一律用**单条 group_by 查询**汇总（缺陷按
category、焊法按 weld_method），内存里查 dict 补齐词表默认 0，避免 per-词条 N+1 查询。
"""

from sqlmodel import Session, func, select

from app.models.analysis import Annotation, Sample
from app.models.data import DataRecord
from app.models.datasets import Dataset
from app.services.jobs import _iso_utc

# 统计口径缺陷词表（§3.2 说明；含未焊透/焊穿/夹渣等，顺序对齐 App.tsx defectTypes）。
DEFECT_VOCAB = ["气孔", "焊瘤", "未焊透", "焊穿", "咬边", "夹渣"]

# weld_method → 熔滴过渡类型（确定性映射：MAG=短路过渡、MIG=射流过渡、TIG=混合过渡、
# 埋弧=脉冲过渡；对齐 App.tsx transitionTypes 词表）。
TRANSITION_BY_WELD_METHOD = {
    "MAG焊": "短路过渡",
    "MIG焊": "射流过渡",
    "TIG焊": "混合过渡",
    "埋弧焊": "脉冲过渡",
    "CMT": "CMT",
}


def get_stats(session: Session) -> dict:
    """统计卡四项，数值从表聚合。

    - data_total = data_records 总数
    - manufacturer_total = distinct machine（焊机品牌）数
    - max_storage_bytes = max(storage_bytes)
    - annotated_samples = 至少有一条标注的 distinct 样本数
    - annotation_completion = annotated_samples / samples 总数 × 100（百分比）
    """
    data_total = _count(session, func.count(DataRecord.id))
    # COUNT(DISTINCT machine)：DISTINCT 天然排除 NULL，无需额外过滤。
    manufacturer_total = _count(
        session, func.count(func.distinct(DataRecord.machine))
    )
    max_bytes = _first_scalar(session, select(func.max(DataRecord.storage_bytes)))
    max_storage_bytes = int(max_bytes) if max_bytes is not None else 0

    total_samples = _count(session, func.count(Sample.id))
    annotated_samples = _count(
        session, func.count(func.distinct(Annotation.sample_id))
    )
    completion = (
        round(annotated_samples / total_samples * 100, 1) if total_samples else 0.0
    )

    return {
        "data_total": data_total,
        "manufacturer_total": manufacturer_total,
        "max_storage_bytes": max_storage_bytes,
        "annotated_samples": annotated_samples,
        "annotation_completion": completion,
    }


def get_attributes(session: Session) -> dict:
    """属性面板四项。

    - weld_methods：焊机种类（distinct machine，字符串列表）
    - defect_types：缺陷种类（统计口径词表 + count，`[{name, count}]`）
    - modalities：多模态种类（distinct modality 名，字符串列表）
    - sample_rate_tiers：采集频率档位（distinct sample_rate，字符串列表）
    """
    weld_methods = sorted(_distinct_scalars(session, DataRecord.machine))

    defect_counts = _defect_counts(session)
    defect_types = [
        {"name": name, "count": defect_counts.get(name, 0)} for name in DEFECT_VOCAB
    ]

    modality_set: set[str] = set()
    for value in session.exec(select(DataRecord.modalities)).all():
        modality_set.update(value or [])
    modalities = sorted(modality_set)

    sample_rate_tiers = sorted(_distinct_scalars(session, DataRecord.sample_rate))

    return {
        "weld_methods": weld_methods,
        "defect_types": defect_types,
        "modalities": modalities,
        "sample_rate_tiers": sample_rate_tiers,
    }


def get_distributions(session: Session) -> dict:
    """分布图数据。

    - manufacturers：厂商比重（制造商名 = machine 品牌前缀，value = 记录数）
    - transition_types：过渡类型（weld_method → 过渡类型映射，value = 记录数）
    - welding_types：焊接类型（distinct weld_method，value = 记录数）
    - defects：缺陷分布（统计口径词表 + count，全词表含 0 计数）
    - wordcloud：厂商词云（制造商名 + size，size 与记录数成正比）
    """
    brand_counts = _brand_counts(session)

    manufacturers = [
        {"name": brand, "value": count}
        for brand, count in sorted(brand_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 单条 group_by 查询拿到 weld_method → 记录数，一次喂给 transition_types 与 welding_types。
    weld_method_counts = _weld_method_counts(session)

    transition: dict[str, int] = {}
    for method, count in weld_method_counts.items():
        t = TRANSITION_BY_WELD_METHOD.get(method, "脉冲过渡")
        transition[t] = transition.get(t, 0) + count
    transition_types = [
        {"name": name, "value": count}
        for name, count in sorted(transition.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    welding_types = [
        {"name": name, "value": count}
        for name, count in sorted(weld_method_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    defect_counts = _defect_counts(session)
    defects = [
        {"name": name, "count": defect_counts.get(name, 0)} for name in DEFECT_VOCAB
    ]

    max_count = max(brand_counts.values()) if brand_counts else 0
    wordcloud = [
        {
            "name": brand,
            "size": _wordcloud_size(count, max_count),
        }
        for brand, count in sorted(brand_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    return {
        "manufacturers": manufacturers,
        "transition_types": transition_types,
        "welding_types": welding_types,
        "defects": defects,
        "wordcloud": wordcloud,
    }


def get_projects(session: Session) -> list[dict]:
    """数据项目卡片：从 `datasets` 派生 `{name, status, sample_count, progress, updated_at}`。

    status/sample_count/progress 原样来自数据集（标注中/可训练、数字样本数、百分比进度）；
    updated_at 为 ISO-8601 UTC 字符串。tone 由前端按 status 映射。
    """
    datasets = session.exec(select(Dataset).order_by(Dataset.id)).all()
    return [
        {
            "name": ds.name,
            "status": ds.status,
            "sample_count": ds.sample_count,
            "progress": float(ds.progress) if ds.progress is not None else 0.0,
            "updated_at": _iso_utc(ds.updated_at),
        }
        for ds in datasets
    ]


# ── 内部聚合助手 ──────────────────────────────────────────────────────


def _count(session: Session, aggregate_expr) -> int:
    """执行 `select(<聚合函数>)`（SelectOfScalar）并取整数值。"""
    return int(session.exec(select(aggregate_expr)).one())


def _first_scalar(session: Session, statement):
    """取 `select(<标量函数>)` 的单个结果（无行时为 None）。"""
    return session.exec(statement).one_or_none()


def _distinct_scalars(session: Session, column) -> list[str]:
    """distinct 单列的非空字符串值列表（SelectOfScalar，.all() 直接给标量）。"""
    return [value for value in session.exec(select(column).distinct()).all() if value]


def _defect_counts(session: Session) -> dict[str, int]:
    """单条 group_by 查询返回 `{category: 标注数}`；统计口径词表缺失类别默认 0。

    多列 select 返回 Row，可 `for cat, cnt in rows` 解包。
    """
    rows = session.exec(
        select(Annotation.category, func.count(Annotation.id)).group_by(
            Annotation.category
        )
    ).all()
    return {category: int(count) for category, count in rows}


def _weld_method_counts(session: Session) -> dict[str, int]:
    """单条 group_by 查询返回 `{weld_method: 记录数}`（NULL 被 group_by 排除）。"""
    rows = session.exec(
        select(DataRecord.weld_method, func.count(DataRecord.id)).group_by(
            DataRecord.weld_method
        )
    ).all()
    return {method: int(count) for method, count in rows if method}


def _brand_counts(session: Session) -> dict[str, int]:
    """按 machine 品牌前缀（首个 token）统计记录数。"""
    counts: dict[str, int] = {}
    for machine in session.exec(select(DataRecord.machine)).all():
        if not machine:
            continue
        brand = machine.split(" ", 1)[0]
        counts[brand] = counts.get(brand, 0) + 1
    return counts


def _wordcloud_size(count: int, max_count: int) -> int:
    """把记录数映射到词云字号（8~34px），与 seed 规模自洽。"""
    if max_count <= 0:
        return 8
    return 8 + round((count / max_count) * 26)
