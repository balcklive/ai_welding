"""关闭「长期 running、且确实没有任何标注成果」的标注任务 Job（一次性运维，2026-09-28）。

**背景**（客户视角审查报告 2026-09-28 P1-04）：线上有 29 个 `annotation` Job 从 9/6 起一直是
`running`（关联任务停在 `ls_status=pending_ls`、28 条 `annotation_ls_sync` 停在 `annotating`）。
根因是"主应用保存标注不会收尾任务"（已修：`POST …/labels` 现在会把样本视作已回写并收尾），
但**存量任务不会自愈**——它们的样本当年一条标注都没提交过。

**判定口径（保守，只关"确实没有成果"的）**：同时满足

1. `jobs.type='annotation'` 且 `status='running'`，`created_at` 早于 `--min-age-days`（默认 3 天）；
2. 该任务的全部样本上 **没有任何** `annotations` 行；
3. 该任务的全部 `annotation_ls_sync` 行里 **没有一条** `synced`。

任何一条不满足就跳过并打印原因——**不批量置成功**（那会谎称有标注成果），也**不改
`annotation_tasks.ls_status`**（`pending_ls` 如实反映"推过 LS、没回来"）。

用法（默认 dry-run，只打印不写库）：

    uv run python scripts/close_stuck_annotation_jobs.py                    # 预览
    uv run python scripts/close_stuck_annotation_jobs.py --min-age-days 1   # 预览（放宽年龄）
    uv run python scripts/close_stuck_annotation_jobs.py --confirm          # 真写

失败整体回滚（一个事务，仅末尾 commit）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ 进 sys.path，便于 import app

from app.core.db import engine  # noqa: E402

#: `jobs.error` 是 **JSON 列**（见 `app/models/jobs.py`），必须写 JSON 对象——写裸字符串会得到
#: MySQL 3140 `Invalid JSON text`（本脚本首次执行时踩过）；前端读的是 `job.error.message`。
CLOSE_REASON = {"message": "标注任务长期无提交且无任何标注成果，人工关闭（详见 2026-09-28 客户视角审查 P1-04）"}


def _candidates(connection, cutoff: datetime) -> list[dict]:
    rows = connection.execute(
        text(
            """
            SELECT j.id AS job_id, j.job_uid, j.created_at, j.progress,
                   at.id AS task_id, at.source, at.ls_status
            FROM jobs j
            JOIN annotation_tasks at ON at.job_id = j.id
            WHERE j.type = 'annotation' AND j.status = 'running' AND j.created_at < :cutoff
            ORDER BY j.created_at
            """
        ),
        {"cutoff": cutoff},
    ).mappings().all()
    return [dict(row) for row in rows]


def _has_results(connection, task_id: int) -> tuple[int, int]:
    annotations = connection.execute(
        text(
            """
            SELECT COUNT(*) FROM annotations a
            JOIN samples s ON s.id = a.sample_id
            WHERE s.annotation_task_id = :task_id
            """
        ),
        {"task_id": task_id},
    ).scalar_one()
    synced = connection.execute(
        text(
            """
            SELECT COUNT(*) FROM annotation_ls_sync
            WHERE annotation_task_id = :task_id AND sync_status = 'synced'
            """
        ),
        {"task_id": task_id},
    ).scalar_one()
    return int(annotations), int(synced)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-age-days", type=int, default=3, help="只关创建时间早于 N 天的任务")
    parser.add_argument("--job-uid", default=None, help="只处理指定 job_uid（逐条核实用）")
    parser.add_argument("--confirm", action="store_true", help="真正写库（缺省只预览）")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.min_age_days)
    closed: list[str] = []
    skipped: list[tuple[str, str]] = []

    with engine.begin() as connection:
        for candidate in _candidates(connection, cutoff):
            job_uid = candidate["job_uid"]
            if args.job_uid and job_uid != args.job_uid:
                continue
            annotations, synced = _has_results(connection, candidate["task_id"])
            if annotations or synced:
                skipped.append((job_uid, f"已有标注 {annotations} 条 / 已回写 {synced} 条，需人工核实"))
                continue
            closed.append(job_uid)
            print(
                f"[close] {job_uid} task={candidate['task_id']} source={candidate['source']} "
                f"ls_status={candidate['ls_status']} created={candidate['created_at']} progress=0"
            )
            if args.confirm:
                connection.execute(
                    text(
                        """
                        UPDATE jobs
                        SET status = 'failed', error = :error, finished_at = :finished_at
                        WHERE id = :job_id AND status = 'running'
                        """
                    ),
                    {
                        "error": json.dumps(CLOSE_REASON, ensure_ascii=False),
                        "finished_at": datetime.now(timezone.utc),
                        "job_id": candidate["job_id"],
                    },
                )
        if not args.confirm:
            raise SystemExit(  # 回滚事务：dry-run 不留下任何写入
                f"\n预览：可关闭 {len(closed)} 个、跳过 {len(skipped)} 个（加 --confirm 才写库）"
            )

    for job_uid, reason in skipped:
        print(f"[skip]  {job_uid}: {reason}")
    print(f"完成：关闭 {len(closed)} 个，跳过 {len(skipped)} 个")


if __name__ == "__main__":
    main()
