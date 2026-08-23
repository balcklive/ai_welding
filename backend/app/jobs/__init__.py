"""Job 执行器 + 各域 handler 注册（Task 13）。

导入本包即触发 `app/jobs/alignment.py` 的模块级 `@register_handler("alignment")`，
使 `executor.HANDLERS` 就绪。lifespan 里 `from app.jobs import executor` 后调
`executor.start()` / `executor.stop()`。
"""

from app.jobs import executor
from app.jobs.alignment import handle as _alignment_handler  # noqa: F401  # 注册 alignment handler
from app.jobs.annotation import handle as _annotation_handler  # noqa: F401  # 注册 annotation handler（Task 14）
from app.jobs.split import handle as _split_handler  # noqa: F401  # 注册 split handler（Task 14）
from app.jobs.dataset_build import handle as _dataset_build_handler  # noqa: F401  # 注册 dataset_build handler（Task 15）

__all__ = [
    "executor",
    "HANDLERS",
    "register_handler",
    "run_job",
    "start",
    "stop",
]

HANDLERS = executor.HANDLERS
register_handler = executor.register_handler
run_job = executor.run_job
start = executor.start
stop = executor.stop
