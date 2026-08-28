"""One-time cleanup of legacy demo/debug records from the production database.

Only records with explicit demo/debug markers or synthetic sample metadata are targeted.
Real uploaded welds, datasets, media and user-created annotation tasks are preserved.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from app.core.db import engine
from app.storage import get_storage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-production-cleanup", action="store_true")
    args = parser.parse_args()
    if not args.confirm_production_cleanup:
        raise SystemExit("Pass --confirm-production-cleanup to delete legacy demo records")

    object_keys: set[str] = set()
    with engine.begin() as connection:
        demo_tasks = connection.execute(
            text("SELECT id, job_id FROM annotation_tasks WHERE name IN ('AN-演示', 'debug-video')")
        ).mappings().all()
        demo_task_ids = [row["id"] for row in demo_tasks]
        demo_job_ids = [row["job_id"] for row in demo_tasks]

        synthetic_rows = connection.execute(
            text("SELECT id, object_keys FROM samples WHERE JSON_EXTRACT(meta, '$.synthetic') = true")
        ).mappings().all()
        synthetic_ids = [row["id"] for row in synthetic_rows]

        for row in [*synthetic_rows]:
            object_keys.update(json.loads(row["object_keys"] or "[]"))
        if demo_task_ids:
            placeholders = ",".join(f":task_{i}" for i in range(len(demo_task_ids)))
            params = {f"task_{i}": value for i, value in enumerate(demo_task_ids)}
            rows = connection.execute(
                text(f"SELECT object_keys FROM samples WHERE annotation_task_id IN ({placeholders})"), params
            ).all()
            for row in rows:
                object_keys.update(json.loads(row[0] or "[]"))

        deleted_sample_ids = sorted(set(synthetic_ids))
        if demo_task_ids:
            placeholders = ",".join(f":task_{i}" for i in range(len(demo_task_ids)))
            params = {f"task_{i}": value for i, value in enumerate(demo_task_ids)}
            connection.execute(text(f"DELETE FROM annotations WHERE sample_id IN (SELECT id FROM samples WHERE annotation_task_id IN ({placeholders}))"), params)
            connection.execute(text(f"DELETE FROM samples WHERE annotation_task_id IN ({placeholders})"), params)
        if deleted_sample_ids:
            placeholders = ",".join(f":sample_{i}" for i in range(len(deleted_sample_ids)))
            params = {f"sample_{i}": value for i, value in enumerate(deleted_sample_ids)}
            connection.execute(text(f"DELETE FROM annotations WHERE sample_id IN ({placeholders})"), params)
            connection.execute(text(f"DELETE FROM dataset_items WHERE sample_id IN ({placeholders})"), params)
            connection.execute(text(f"DELETE FROM samples WHERE id IN ({placeholders})"), params)

        # The only current dataset version made exclusively from synthetic samples.
        synthetic_versions = connection.execute(
            text("SELECT id, snapshot_id FROM dataset_versions WHERE id = 3 AND item_count > 0")
        ).mappings().all()
        for row in synthetic_versions:
            if row["snapshot_id"]:
                object_keys.add(row["snapshot_id"])
            connection.execute(text("UPDATE datasets SET current_version_id = NULL WHERE current_version_id = :id"), {"id": row["id"]})
            build_job_ids = connection.execute(
                text("SELECT job_id FROM dataset_build_tasks WHERE dataset_version_id = :id"),
                {"id": row["id"]},
            ).scalars().all()
            connection.execute(text("DELETE FROM dataset_build_tasks WHERE dataset_version_id = :id"), {"id": row["id"]})
            connection.execute(text("DELETE FROM dataset_versions WHERE id = :id"), {"id": row["id"]})
            connection.execute(text("DELETE FROM audit_logs WHERE resource_id = 'job_41909bc6'"))
            connection.execute(text("DELETE FROM jobs WHERE job_uid = 'job_41909bc6'"))

        if demo_job_ids:
            placeholders = ",".join(f":job_{i}" for i in range(len(demo_job_ids)))
            params = {f"job_{i}": value for i, value in enumerate(demo_job_ids)}
            job_uids = connection.execute(text(f"SELECT job_uid FROM jobs WHERE id IN ({placeholders})"), params).scalars().all()
            connection.execute(text(f"DELETE FROM annotation_tasks WHERE id IN ({','.join(f':task_{i}' for i in range(len(demo_task_ids)))})"), {f"task_{i}": value for i, value in enumerate(demo_task_ids)})
            connection.execute(text(f"DELETE FROM jobs WHERE id IN ({placeholders})"), params)
            if job_uids:
                uid_params = {f"uid_{i}": value for i, value in enumerate(job_uids)}
                connection.execute(text(f"DELETE FROM audit_logs WHERE resource_id IN ({','.join(f':uid_{i}' for i in range(len(job_uids)))})"), uid_params)

        model_rows = connection.execute(
            text("SELECT id FROM models WHERE name IN ('焊接异常检测模型', '熔池分割模型', '质量预测模型')")
        ).scalars().all()
        if model_rows:
            placeholders = ",".join(f":model_{i}" for i in range(len(model_rows)))
            params = {f"model_{i}": value for i, value in enumerate(model_rows)}
            version_rows = connection.execute(text(f"SELECT file_key FROM model_versions WHERE model_id IN ({placeholders})"), params).scalars().all()
            object_keys.update(value for value in version_rows if value)
            connection.execute(text(f"DELETE FROM model_versions WHERE model_id IN ({placeholders})"), params)
            connection.execute(text(f"DELETE FROM models WHERE id IN ({placeholders})"), params)
            connection.execute(text("DELETE FROM audit_logs WHERE resource_type = 'model' AND resource_id IN ('焊接异常检测模型','熔池分割模型','质量预测模型')"))

    failed: list[str] = []
    storage = get_storage()
    for key in sorted(object_keys):
        try:
            storage.delete_object(key)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{key}: {exc}")
    print(json.dumps({"deleted_object_count": len(object_keys), "storage_failures": failed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
