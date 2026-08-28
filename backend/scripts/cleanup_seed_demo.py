"""一次性清理：删除线上库中由 app/core/seed.py 灌入的演示数据。

范围（保留真实数据：data_records 6/7、dataset 1 及其关联）：
- 演示焊缝 data_records 2~5（WLD-202608xx-0245~0248）及其 data_versions、
  核验（validation_reports + rule_results）、信号 ingest、对齐/切分任务、
  标注任务/样本/标注、特征提取、关联 Jobs
- 演示数据集 datasets 2,3（熔池分割数据集/工艺质量预测集）及其 dataset_versions、
  构建任务（dataset_items 本就为 0）
- 演示模型 models 1~3 及 model_versions、训练/测试/推理任务、关联 Jobs

用法：uv run python scripts/cleanup_seed_demo.py [--dry-run]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ 进 sys.path，便于 import app

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.core.db import engine  # noqa: E402

DEMO_RECORD_IDS = [2, 3, 4, 5]  # 0248/0247/0246/0245（真实数据 6,7 保留）
DEMO_DATASET_IDS = [2, 3]  # 熔池分割数据集 / 工艺质量预测集（真实 dataset 1 保留）
DEMO_MODEL_IDS = [1, 2, 3]  # 焊接异常检测模型/熔池分割模型/质量预测模型


def main(dry_run: bool) -> None:
    with Session(engine) as session:
        def ids(sql: str) -> list[int]:
            return [r[0] for r in session.execute(text(sql))]

        rid = ",".join(map(str, DEMO_RECORD_IDS))
        did = ",".join(map(str, DEMO_DATASET_IDS))
        mid = ",".join(map(str, DEMO_MODEL_IDS))

        vid = ",".join(map(str, ids(f"SELECT id FROM data_versions WHERE record_id IN ({rid})"))) or "0"
        stid = ",".join(map(str, ids(f"SELECT id FROM split_tasks WHERE version_id IN ({vid})"))) or "0"
        atid = ",".join(map(str, ids(f"SELECT id FROM annotation_tasks WHERE split_task_id IN ({stid})"))) or "0"
        sid = ",".join(map(str, ids(
            f"SELECT id FROM samples WHERE split_task_id IN ({stid}) OR annotation_task_id IN ({atid})"))) or "0"
        repid = ",".join(map(str, ids(f"SELECT id FROM validation_reports WHERE version_id IN ({vid})"))) or "0"
        dvid = ",".join(map(str, ids(f"SELECT id FROM dataset_versions WHERE dataset_id IN ({did})"))) or "0"
        mvid = ",".join(map(str, ids(f"SELECT id FROM model_versions WHERE model_id IN ({mid})"))) or "0"

        job_ids: set[int] = set()
        for sql in [
            f"SELECT job_id FROM signal_ingests WHERE job_id IS NOT NULL AND version_id IN ({vid})",
            f"SELECT job_id FROM alignment_tasks WHERE job_id IS NOT NULL AND version_id IN ({vid})",
            f"SELECT job_id FROM split_tasks WHERE job_id IS NOT NULL AND id IN ({stid})",
            f"SELECT job_id FROM annotation_tasks WHERE job_id IS NOT NULL AND id IN ({atid})",
            f"SELECT job_id FROM dataset_build_tasks WHERE job_id IS NOT NULL AND dataset_version_id IN ({dvid})",
            f"SELECT job_id FROM training_tasks WHERE job_id IS NOT NULL AND (dataset_version_id IN ({dvid}) OR base_model_id IN ({mvid}))",
            f"SELECT job_id FROM test_tasks WHERE job_id IS NOT NULL AND (model_version_id IN ({mvid}) OR dataset_version_id IN ({dvid}))",
            f"SELECT job_id FROM inference_tasks WHERE job_id IS NOT NULL AND model_version_id IN ({mvid})",
        ]:
            job_ids.update(ids(sql))
        jid = ",".join(map(str, sorted(job_ids))) or "0"

        plan = [
            ("annotations", f"sample_id IN ({sid})"),
            ("samples", f"id IN ({sid})"),
            ("annotation_tasks", f"id IN ({atid})"),
            ("split_tasks", f"id IN ({stid})"),
            ("alignment_tasks", f"version_id IN ({vid})"),
            ("signal_ingests", f"version_id IN ({vid})"),
            ("validation_rule_results", f"report_id IN ({repid})"),
            ("validation_reports", f"id IN ({repid})"),
            ("feature_extractions", f"version_id IN ({vid})"),
            ("dataset_build_tasks", f"dataset_version_id IN ({dvid})"),
            ("training_tasks", f"dataset_version_id IN ({dvid}) OR base_model_id IN ({mvid})"),
            ("test_tasks", f"model_version_id IN ({mvid}) OR dataset_version_id IN ({dvid})"),
            ("inference_tasks", f"model_version_id IN ({mvid})"),
            ("model_versions", f"id IN ({mvid})"),
            ("models", f"id IN ({mid})"),
            ("data_records.latest_version_id←NULL", f"UPDATE data_records SET latest_version_id = NULL WHERE id IN ({rid})"),
            ("data_versions", f"id IN ({vid})"),
            ("data_records", f"id IN ({rid})"),
            # 演示焊缝引用演示数据集（data_records.dataset_id），须先删焊缝再删数据集；
            # 真实焊缝若误挂在演示数据集下（如 REG-20260815-00004 挂在 工艺质量预测集），
            # 挪回真实数据集 SP2026 焊接批次数据（id=1），避免随假数据集一起被 FK 卡住
            ("data_records.dataset_id→1", f"UPDATE data_records SET dataset_id = 1 WHERE dataset_id IN ({did})"),
            # datasets.current_version_id ↔ dataset_versions 环引用：先置空再删版本/数据集
            ("datasets.current_version_id←NULL", f"UPDATE datasets SET current_version_id = NULL WHERE id IN ({did})"),
            ("dataset_versions", f"id IN ({dvid})"),
            ("datasets", f"id IN ({did})"),
            ("jobs", f"id IN ({jid})"),
        ]
        total = 0
        for tbl, where in plan:
            if where.upper().startswith("UPDATE"):
                n = session.execute(text(where)).rowcount
                print(f"{tbl:24s} ~{n}")
                continue
            n = session.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE {where}")).scalar_one()
            print(f"{tbl:24s} -{n}")
            total += n
            if not dry_run and n:
                session.execute(text(f"DELETE FROM {tbl} WHERE {where}"))
        print(f"total rows: {total}")
        if dry_run:
            session.rollback()
            print("[dry-run] Rolled back; remove --dry-run to execute deletion")
        else:
            session.commit()
            print("committed.")
        for tbl in ["datasets", "dataset_versions", "data_records", "data_versions", "models", "model_versions", "jobs"]:
            left = ids(f"SELECT id FROM {tbl}")
            print(f"remaining {tbl}: {left}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
