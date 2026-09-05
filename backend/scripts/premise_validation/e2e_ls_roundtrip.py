"""Real e2e: 真实样本 -> 推 LS -> 本机模拟 webhook 回写 -> 幂等校验（真实 LS + 真实 MySQL + 真实 MinIO）。

覆盖路径（真实):
  - 建 Job + AnnotationTask(ls_status=pending_ls) + Sample（真实样本，对象在 MinIO）
  - annotation_ls.push_samples_to_ls  → 真实 SDK 建 LS task（box→项目3 / polygon→项目4）
  - SDK 在该 LS task 上建真实标注（rectanglelabels / polygonlabels）
  - 本机模拟 webhook：直接调 annotation_ls.handle_annotation_event（真实拉取+转换+回写）
  - 校验回写 annotations（category/kind/几何/annotator）+ 幂等（重复事件不重复落行）
收尾：删除 LS task + 清理 DB 测试行 + 清理 MinIO 测试对象。

只在你想打真实环境时跑：
  cd backend && uv run python scripts/premise_validation/e2e_ls_roundtrip.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import traceback
import uuid
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

os.environ.setdefault("LABEL_STUDIO_MODE", "on")
os.environ.setdefault("LABEL_STUDIO_INTERNAL_URL", "http://182.61.59.135:8224")
os.environ.setdefault("LABEL_STUDIO_PUBLIC_URL", "http://182.61.59.135:8224")
os.environ.setdefault("LABEL_STUDIO_WEBHOOK_SECRET", "e2e-ls-secret")

import io  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402
from sqlmodel import select  # noqa: E402

from app import storage  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.integrations import labelstudio as ls  # noqa: E402
from app.models.analysis import (  # noqa: E402
    Annotation,
    AnnotationLsSync,
    AnnotationTask,
    Sample,
)
from app.models.jobs import Job  # noqa: E402
from app.services import annotation_ls  # noqa: E402
from app.services.jobs import create_job  # noqa: E402
from label_studio_sdk import LabelStudio  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_png(w: int = 640, h: int = 480) -> bytes:
    img = Image.new("RGB", (w, h), (40, 44, 52))
    draw = ImageDraw.Draw(img)
    draw.rectangle([140, 120, 360, 300], fill=(60, 140, 90))
    draw.ellipse([440, 60, 560, 180], fill=(90, 90, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def presign_image(stow, blob: bytes) -> tuple[str, str]:
    key = f"e2e/{uuid.uuid4().hex}/frame.png"
    stow.upload_stream(key, io.BytesIO(blob), len(blob), "image/png")
    return key, stow.presign_get(key)


def make_sample_fixture(session, task, key: str, meta: dict) -> Sample:
    sample = Sample(annotation_task_id=task.id, object_keys=[key], meta=meta)
    session.add(sample)
    session.flush()
    return sample


def make_task(session, source: str) -> tuple[Job, AnnotationTask]:
    job = create_job(session, type="annotation")
    job.status = "running"  # LS 等待态：不进 executor 领单队列
    job.progress = 0
    session.add(job)
    task = AnnotationTask(job_id=job.id, source=source, ls_status="pending_ls", created_at=_now())
    session.add(task)
    session.flush()
    return job, task


def ls_region_for(project: int) -> dict:
    """按项目构造真实 rectangle/polygon region（0-100 百分比）。"""
    if project == 3:  # RectangleLabels
        return {
            "id": f"e2e-box-{uuid.uuid4().hex[:6]}",
            "type": "rectanglelabels",
            "from_name": "label",
            "to_name": "image",
            "original_width": 640,
            "original_height": 480,
            "image_rotation": 0,
            "value": {"x": 12.5, "y": 20.0, "width": 30.0, "height": 25.0, "rectanglelabels": ["气孔"]},
        }
    if project == 4:  # PolygonLabels
        return {
            "id": f"e2e-poly-{uuid.uuid4().hex[:6]}",
            "type": "polygonlabels",
            "from_name": "label",
            "to_name": "image",
            "original_width": 640,
            "original_height": 480,
            "image_rotation": 0,
            "value": {
                "points": [[10.0, 20.0], [40.0, 20.0], [40.0, 50.0], [10.0, 50.0]],
                "polygonlabels": ["熔池"],
                "closed": True,
            },
        }
    raise ValueError(f"unsupported ls project for e2e: {project}")


def run_roundtrip(session, client, stow, cleanup, label, *, source: str, meta: dict, project: int) -> dict:
    """一个任务的完整回写：建 task/sample → 推 LS → SDK 标注 → 模拟 webhook → 幂等。

    `cleanup` 为列表，函数内每建一个资源即登记，供 finally 兜底清理。
    """
    blob = make_png()
    key, url = presign_image(stow, blob)
    job, task = make_task(session, source)
    sample = make_sample_fixture(session, task, key, meta)
    cleanup.append({"job_id": job.id, "task_id": task.id, "sample_id": sample.id,
                    "ls_task_id": None, "object_key": key})

    # 推 LS（真实建 task）
    created = annotation_ls.push_samples_to_ls(session, task, [sample])
    sync_row = session.exec(
        select(AnnotationLsSync).where(AnnotationLsSync.annotation_task_id == task.id,
                                       AnnotationLsSync.sample_id == sample.id)
    ).first()
    ls_task_id = sync_row.ls_task_id if sync_row else None
    assert created == 1 and ls_task_id, f"{label}: push_samples_to_ls failed (created={created}, ls_task_id={ls_task_id})"
    cleanup[-1]["ls_task_id"] = int(ls_task_id)
    print(f"[{label}] pushed -> LS task id={ls_task_id} project={project}")

    # SDK 在 LS 建真实标注
    region = ls_region_for(project)
    client.annotations.create(
        int(ls_task_id),
        result=[region],
        task=int(ls_task_id),
        completed_by=1,
    )
    print(f"[{label}] SDK annotation created on LS task {ls_task_id}")

    # 本机模拟 webhook：直接调生产 service 代码路径
    res = annotation_ls.handle_annotation_event(session, "annotation_created", {"task": {"id": ls_task_id}})
    session.flush()
    assert res and res["samples"] == 1, f"{label}: handle_annotation_event returned {res}"

    anns = session.exec(select(Annotation).where(Annotation.sample_id == sample.id)).all()
    assert len(anns) == 1, f"{label}: expected 1 written annotation, got {len(anns)}"
    ann = anns[0]
    expected_cat = "熔池" if project == 4 else "气孔"
    assert ann.category == expected_cat, f"{label}: category={ann.category!r} != {expected_cat!r}"
    kind = "polygon" if project == 4 else "box"
    assert ann.kind == kind, f"{label}: kind={ann.kind!r} != {kind!r}"
    print(f"[{label}] writeback OK: kind={ann.kind} category={ann.category} annotator={ann.annotator} "
          f"box={ann.box} points={ann.points}")

    # 状态联动
    sync_row = session.exec(select(AnnotationLsSync).where(AnnotationLsSync.ls_task_id == int(ls_task_id))).first()
    task = session.get(AnnotationTask, task.id)
    assert sync_row.sync_status == "synced", f"{label}: sync_status={sync_row.sync_status}"
    assert task.ls_status == "synced", f"{label}: task.ls_status={task.ls_status}"

    # 幂等：重复 webhook 不重复落行
    annotation_ls.handle_annotation_event(session, "annotation_updated", {"task": {"id": ls_task_id}})
    session.flush()
    after = session.exec(select(Annotation).where(Annotation.sample_id == sample.id)).all()
    assert len(after) == 1, f"{label}: idempotency broken, got {len(after)} annotations after re-fire"
    print(f"[{label}] idempotency OK (re-fire kept {len(after)} annotation row(s))")

    return {"task_id": task.id, "sample_id": sample.id, "job_id": job.id,
            "ls_task_id": int(ls_task_id), "object_key": key}


def main() -> int:
    client = LabelStudio(base_url=settings.label_studio_internal_url,
                         api_key=settings.label_studio_api_key)
    stow = storage.get_storage()
    cleanup: list[dict] = []
    dbs: list[dict] = []
    with SessionLocal() as session:
        try:
            # box（项目3，目标检测）
            dbs.append(run_roundtrip(session, client, stow, cleanup, "BOX", source="manual",
                                     meta={"mode": "image"}, project=3))
            # polygon（项目4，熔池分割）
            dbs.append(run_roundtrip(session, client, stow, cleanup, "POLY", source="video",
                                     meta={"mode": "frame", "frame_width": 640, "frame_height": 480}, project=4))
            session.commit()
            print("\n=== e2e SUCCESS ===")
            print(json.dumps(dbs, ensure_ascii=False, indent=2))
            return 0
        except Exception:
            traceback.print_exc()
            session.rollback()
            print("\n=== e2e FAILED ===")
            return 1
        finally:
            # 清理 LS task + DB 测试行 + MinIO 测试对象（逆序）
            for r in reversed(cleanup):
                _cleanup_row(session, client, stow, r)
            session.commit()
            print("cleanup done")


def _cleanup_row(session, client, stow, r: dict) -> None:
    try:
        if r.get("ls_task_id"):
            ls.delete_task(client, int(r["ls_task_id"]))
    except Exception as exc:  # noqa: BLE001
        print(f"cleanup ls task {r.get('ls_task_id')} failed: {exc}")
    try:
        if r.get("sample_id"):
            for a in session.exec(select(Annotation).where(Annotation.sample_id == r["sample_id"])).all():
                session.delete(a)
        if r.get("ls_task_id"):
            sync = session.exec(select(AnnotationLsSync).where(AnnotationLsSync.ls_task_id == int(r["ls_task_id"]))).first()
            if sync:
                session.delete(sync)
        if r.get("sample_id"):
            sample = session.get(Sample, r["sample_id"])
            if sample:
                session.delete(sample)
        if r.get("task_id"):
            task = session.get(AnnotationTask, r["task_id"])
            if task:
                session.delete(task)
        if r.get("job_id"):
            job = session.get(Job, r["job_id"])
            if job:
                session.delete(job)
    except Exception as exc:  # noqa: BLE001
        print(f"cleanup db rows for sample {r.get('sample_id')} failed: {exc}")
    try:
        if r.get("object_key"):
            stow.delete_object(r["object_key"])
    except Exception as exc:  # noqa: BLE001
        print(f"cleanup minio {r.get('object_key')} failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
