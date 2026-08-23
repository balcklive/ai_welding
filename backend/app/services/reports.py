"""通用报告导出服务（Task 17）。

契约：`docs/API接口清单.md` §3.7（POST /reports/export）+ `docs/OSS存储设计.md` §2
（对象键 `reports/{report_type}/{ref_id}.pdf|.json`）。

- `export_reports(session, report_type, ref_ids, fmt)` 为路由层唯一入口：
  每个 `ref_id` 装配报告内容 → 渲染字节 → `upload_stream` 写 MinIO →
  `presign_get` 签发下载 URL → 返回 `[{ref_id, url}, ...]`。
- **PDF 渲染复用 Jinja2 + xhtml2pdf**（开发规范 §1 复用清单）：HTML 模板在
  `app/templates/reports/`，`validation` / `data-list` 有真实模板，其余类型
  （analysis / annotation / features / test）复用 `generic.html.j2`（渲染可用的
  摘要 + 分节明细，无数据则显示占位）。
- `format=json` 时把同一份装配内容 dict 直接落 `{ref_id}.json`。

错误语义：
- `ValueError`（未知类型/格式）→ 路由层 400（40000）；
- `EntityNotFoundError`（引用的实体不存在）→ 路由层 404（40401）。
- 写 MinIO 失败抛异常由全局处理器兜底 50000；与 dataset 快照/模型权重的
  "尽力而为跳过"策略不同——导出必须拿到 URL 才返回。

`data-list` 特殊语义：`ref_ids=[]` 表示导出全量数据列表（单份报告，ref_id=`all`）；
`ref_ids` 非空时为记录标识（DB id / weld_id / registration_no）逐一解析，
产出一份过滤后的"数据列表"报告，任一不存在 → 404。
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func
from sqlmodel import Session, select
from xhtml2pdf import pisa

from app.models import (
    AnnotationTask,
    DataRecord,
    DataVersion,
    FeatureExtraction,
    Sample,
    TestTask,
    ValidationReport,
    ValidationRuleResult,
)
from app.services.jobs import _iso_utc

#: 合法报告类型（对齐 `API接口清单.md` §3.7 的 type 枚举）。
REPORT_TYPES = ("validation", "analysis", "annotation", "features", "test", "data-list")
#: 合法导出格式。
FORMATS = ("pdf", "json")

_CONTENT_TYPE_JSON = "application/json"
_CONTENT_TYPE_PDF = "application/pdf"

#: 各类型 PDF 模板（无真实模板的类型统一走 generic）。
_TEMPLATE_BY_TYPE = {
    "validation": "validation.html.j2",
    "data-list": "data_list.html.j2",
    "analysis": "generic.html.j2",
    "annotation": "generic.html.j2",
    "features": "generic.html.j2",
    "test": "generic.html.j2",
}

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "reports"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


class EntityNotFoundError(Exception):
    """引用的实体不存在（路由层映射 40401）。"""


def export_reports(
    session: Session, report_type: str, ref_ids: list, fmt: str
) -> list[dict]:
    """为每个 ref_id 导出一份报告，返回 `[{ref_id, url}]`。

    `data-list` 是整表语义：空 `ref_ids` 导出全量（单份，ref_id=`all`），
    非空则逐标识解析（含 404 语义），产出一份过滤后的列表报告。
    """
    if report_type not in REPORT_TYPES:
        raise ValueError(f"未知报告类型: {report_type}")
    if fmt not in FORMATS:
        raise ValueError(f"未知导出格式: {fmt}")

    if report_type == "data-list":
        return [_export_one(session, report_type, None, fmt, list(ref_ids))]
    return [_export_one(session, report_type, ref_id, fmt) for ref_id in ref_ids]


# ── 导出主流程 ──────────────────────────────────────────────────────


def _export_one(
    session: Session,
    report_type: str,
    ref_id: Any,
    fmt: str,
    data_list_ref_ids: list | None = None,
) -> dict:
    """装配单份报告 → 渲染 → 写 MinIO → 预签名 URL。"""
    if report_type == "data-list":
        data, key_ref = _build_data_list(session, data_list_ref_ids or [])
    else:
        data = _BUILDERS[report_type](session, ref_id)
        key_ref = str(ref_id)
    data["generated_at"] = _iso_utc(datetime.now(timezone.utc))

    if fmt == "json":
        object_key = _object_key(report_type, key_ref, "json")
        _upload(object_key, _json_bytes(data), _CONTENT_TYPE_JSON)
    else:
        object_key = _object_key(report_type, key_ref, "pdf")
        _upload(object_key, _render_pdf(report_type, data), _CONTENT_TYPE_PDF)
    return {"ref_id": key_ref, "url": _presigned(object_key)}


def _object_key(report_type: str, ref_id: str, ext: str) -> str:
    """对象键 `reports/{type}/{ref_id}.{ext}`（OSS §2）。"""
    from app.storage.client import normalize_key  # 延迟导入（同 datasets/models）

    return normalize_key(f"reports/{report_type}", f"{ref_id}.{ext}")


def _upload(object_key: str, data: bytes, content_type: str) -> None:
    from app.storage import get_storage  # 延迟导入，便于测试 monkeypatch

    get_storage().upload_stream(object_key, io.BytesIO(data), len(data), content_type)


def _presigned(object_key: str) -> str:
    from app.storage import get_storage  # 延迟导入，便于测试 monkeypatch

    return get_storage().presign_get(object_key)


def _json_bytes(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")


def _render_pdf(report_type: str, data: dict) -> bytes:
    """Jinja2 模板渲染 HTML → xhtml2pdf → PDF 字节。"""
    template = _env.get_template(_TEMPLATE_BY_TYPE[report_type])
    html = template.render(data)
    out = io.BytesIO()
    status = pisa.CreatePDF(html, dest=out, encoding="utf-8")
    if status.err:
        raise RuntimeError(f"PDF 渲染失败: {status.err}")
    return out.getvalue()


# ── 内容装配（各类型 builder） ─────────────────────────────────────


def _build_validation(session: Session, ref_id: Any) -> dict:
    """核验报告：validation_reports + rule_results（完整模板）。"""
    report = _get_by_int(session, ValidationReport, ref_id, "核验报告")
    rules = session.exec(
        select(ValidationRuleResult)
        .where(ValidationRuleResult.report_id == report.id)
        .order_by(ValidationRuleResult.id)
    ).all()
    version = session.get(DataVersion, report.version_id) if report.version_id else None
    record = session.get(DataRecord, version.record_id) if version else None
    return {
        "title": "焊缝数据核验报告",
        "ref_id": str(ref_id),
        "report_id": report.id,
        "version_id": report.version_id,
        "version_no": version.version_no if version else None,
        "weld_id": record.weld_id if record else None,
        "registration_no": record.registration_no if record else None,
        "score": float(report.score),
        "passed": report.passed,
        "warning": report.warning,
        "failed": report.failed,
        "duration": _num(report.duration),
        "created_at": _iso_utc(report.created_at),
        "rules": [
            {"rule_name": r.rule_name, "status": r.status, "message": r.message or ""}
            for r in rules
        ],
    }


def _build_data_list(session: Session, ref_ids: list) -> tuple[dict, str]:
    """数据列表：`ref_ids=[]` → 全量（ref_id=`all`）；非空 → 逐标识解析过滤。"""
    if ref_ids:
        records: list[DataRecord] = []
        key_parts: list[str] = []
        seen: set[int] = set()
        for ref in ref_ids:
            record = _resolve_record(session, ref)
            if record.id in seen:  # 同一条记录重复引用只出一行
                continue
            seen.add(record.id)
            records.append(record)
            key_parts.append(str(ref))
        ref_id = "-".join(key_parts) or "all"
        items = [_record_item(r) for r in records]
    else:
        records = session.exec(select(DataRecord).order_by(DataRecord.id)).all()
        ref_id = "all"
        items = [_record_item(r) for r in records]
    return {
        "title": "数据列表报告",
        "ref_id": ref_id,
        "items": items,
        "total": len(items),
    }, ref_id


def _build_features(session: Session, ref_id: Any) -> dict:
    """特征集报告：feature_extractions（generic 模板，真实数据）。"""
    ex = _get_by_int(session, FeatureExtraction, ref_id, "特征提取记录")
    version = session.get(DataVersion, ex.version_id) if ex.version_id else None
    record = session.get(DataRecord, version.record_id) if version else None
    uv = ex.unified_vector or {}
    values = uv.get("values") or []
    return {
        "title": "特征提取报告",
        "ref_id": str(ref_id),
        "summary": [
            {"label": "焊缝", "value": record.weld_id if record else "—"},
            {"label": "版本", "value": version.version_no if version else "—"},
            {"label": "归一化", "value": ex.normalization},
            {"label": "格式", "value": ex.format},
            {"label": "向量维度", "value": uv.get("total_dims", len(values))},
            {"label": "提取时间", "value": _iso_utc(ex.created_at) or "—"},
        ],
        "sections": [
            _kv_section("统一向量", values),
            _kv_section("时序特征", _flatten_nested(ex.ts_features)),
            _kv_section("视觉特征", _flatten(ex.vision_features)),
            _kv_section("声音特征", _flatten(ex.audio_features)),
        ],
    }


def _build_test(session: Session, ref_id: Any) -> dict:
    """测试报告：test_tasks.metrics + confusion_matrix（generic 模板，真实数据）。"""
    task = _get_by_int(session, TestTask, ref_id, "测试任务")
    return {
        "title": "模型测试报告",
        "ref_id": str(ref_id),
        "summary": [
            {"label": "模型版本", "value": task.model_version_id},
            {"label": "数据集版本", "value": task.dataset_version_id},
        ],
        "sections": [
            _kv_section("测试指标", task.metrics or {}),
            {
                "heading": "混淆矩阵",
                "items": _flatten_matrix(task.confusion_matrix),
            },
        ],
    }


def _build_annotation(session: Session, ref_id: Any) -> dict:
    """标注集报告：annotation_tasks + 样本数（generic 模板，真实数据）。"""
    task = _get_by_int(session, AnnotationTask, ref_id, "标注任务")
    sample_count = _count_samples(session, task.id)
    return {
        "title": "标注集报告",
        "ref_id": str(ref_id),
        "summary": [
            {"label": "任务名称", "value": task.name or "—"},
            {"label": "来源", "value": task.source},
            {"label": "样本数", "value": sample_count},
            {"label": "创建时间", "value": _iso_utc(task.created_at) or "—"},
        ],
        "sections": [],
    }


def _build_analysis(session: Session, ref_id: Any) -> dict:
    """分析报告：数据版本 + 确定性分析结果（generic 模板）。"""
    version = _get_by_int(session, DataVersion, ref_id, "数据版本")
    record = session.get(DataRecord, version.record_id) if version.record_id else None
    weld_id = record.weld_id if record else None
    # 懒加载 signals（导入较重）；确定性结果源自信号生成器，无需重算完整通道。
    from app.services.signals import analysis_result, generate_signals

    result = analysis_result(generate_signals(weld_id)) if weld_id else {}
    anomalies = result.get("anomalies") or []
    return {
        "title": "分析报告",
        "ref_id": str(ref_id),
        "summary": [
            {"label": "焊缝", "value": weld_id or "—"},
            {"label": "登记号", "value": record.registration_no if record else "—"},
            {"label": "版本", "value": version.version_no},
            {"label": "操作", "value": version.action},
        ],
        "sections": [
            _kv_section("分析结论", _pick(result, "stability", "segments")),
            {
                "heading": "异常区段",
                "items": [
                    {
                        "label": f"[{a.get('start', '')}s, {a.get('end', '')}s]",
                        "value": a.get("type", ""),
                    }
                    for a in anomalies
                ],
            },
        ],
    }


# ── 装配辅助 ────────────────────────────────────────────────────────


def _get_by_int(session: Session, model: type, ref_id: Any, label: str):
    """ref_id 按 int 主键取实体；非整数/不存在 → EntityNotFoundError。"""
    try:
        pk = int(ref_id)
    except (TypeError, ValueError):
        raise EntityNotFoundError(f"{label}不存在: {ref_id}") from None
    obj = session.get(model, pk)
    if obj is None:
        raise EntityNotFoundError(f"{label}不存在: {ref_id}")
    return obj


def _resolve_record(session: Session, ref: Any) -> DataRecord:
    """记录标识解析：int / 数字字符串 → DB id；其余按 weld_id / registration_no。"""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        record = session.get(DataRecord, int(ref))
        if record is None:
            raise EntityNotFoundError(f"数据记录不存在: {ref}")
        return record
    record = session.exec(
        select(DataRecord).where(
            (DataRecord.weld_id == str(ref)) | (DataRecord.registration_no == str(ref))
        )
    ).first()
    if record is None:
        raise EntityNotFoundError(f"数据记录不存在: {ref}")
    return record


def _count_samples(session: Session, annotation_task_id: int) -> int:
    """统计标注任务下样本数（一条 COUNT 查询，避免 N+1）。"""
    return int(
        session.exec(
            select(func.count())
            .select_from(Sample)
            .where(Sample.annotation_task_id == annotation_task_id)
        ).one()
    )


def _record_item(record: DataRecord) -> dict:
    return {
        "weld_id": record.weld_id,
        "registration_no": record.registration_no,
        "weld_name": record.weld_name,
        "source": record.source,
        "machine": record.machine,
        "weld_method": record.weld_method,
        "material": record.material,
        "quality": record.quality,
        "operator": record.operator,
    }


def _num(value) -> float | None:
    return float(value) if value is not None else None


def _kv_section(heading: str, mapping: dict | list) -> dict:
    """`{heading, items:[{label, value}]}`：dict 按键值对展开，list 按序号展开。"""
    if isinstance(mapping, dict):
        items = [{"label": str(k), "value": _fmt(v)} for k, v in mapping.items()]
    else:
        items = [{"label": f"#{i}", "value": _fmt(v)} for i, v in enumerate(mapping)]
    return {"heading": heading, "items": items}


def _flatten(mapping: dict | None) -> dict:
    return {k: v for k, v in (mapping or {}).items()}


def _flatten_nested(mapping: dict | None) -> dict:
    """把 `{通道: {特征: 值}}` 拍平成 `{通道.特征: 值}`（Jinja 直接渲染友好）。"""
    out: dict = {}
    for ch, features in (mapping or {}).items():
        if isinstance(features, dict):
            for k, v in features.items():
                out[f"{ch}.{k}"] = v
        else:
            out[str(ch)] = features
    return out


def _flatten_matrix(cm: Any) -> list:
    """混淆矩阵 2D 列表 → 行式项列表（generic 模板的 `{label,value}`）。"""
    if not isinstance(cm, list):
        return []
    return [
        {"label": f"第 {i + 1} 行", "value": _fmt(row)}
        for i, row in enumerate(cm)
        if isinstance(row, list)
    ]


def _pick(mapping: dict, *keys: str) -> dict:
    return {k: mapping[k] for k in keys if k in mapping}


def _fmt(value: Any) -> Any:
    """展示友好的值格式化：dict/list → JSON 串，Decimal/float 规范化。"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


#: 类型 → builder 映射（export_reports 分派用）。
_BUILDERS = {
    "validation": _build_validation,
    "features": _build_features,
    "test": _build_test,
    "annotation": _build_annotation,
    "analysis": _build_analysis,
}
