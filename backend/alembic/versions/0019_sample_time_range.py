"""样本时间窗落列：`samples` 增 `start_time` / `end_time` 与复合索引。

背景（见 `docs/多模态时间统一样本分段重构设计方案.md` §3.3/§6.2）：v3 起一个 `Sample`
代表一个**时间窗**，窗口起止是它的主键。此前这些信息只存在 `samples.meta`（JSON）里——
按时间筛选切片就得对 JSON 做全表扫描，几万切片时不可接受。

故把时间窗提升为两个真列，并建 `(split_task_id, start_time)` 复合索引：
任务内的切片按时间排序/区间筛选走索引，跨任务的按焊缝时间轴查询也能用上任务前缀。

历史兼容：两列均 nullable，`rules_version <= 2` 的旧样本不回填（它们的时间语义不同——
那时的 `frame_no` 是采样点下标，与 v3 的统一时间轴不是一回事，硬填会伪造出错误的时间窗）。
读侧对 NULL 有兜底（回落 `meta`）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("samples", sa.Column("start_time", sa.Double(), nullable=True))
    op.add_column("samples", sa.Column("end_time", sa.Double(), nullable=True))
    op.create_index(
        "ix_samples_split_task_start", "samples", ["split_task_id", "start_time"]
    )
    # §3.4：`task_format` 从切分规则与任务实体中废弃——v3 不再有"目标检测/时序分类"的
    # 二选一产物，新任务写 NULL。历史行保留原值，其产物口径不受影响。
    op.alter_column(
        "split_tasks", "task_format", existing_type=sa.String(length=32), nullable=True
    )


def downgrade() -> None:
    # 回滚前先把 NULL 补成历史默认值，否则 NOT NULL 加不回去（v3 任务本就写 NULL）
    op.execute("UPDATE split_tasks SET task_format = '目标检测' WHERE task_format IS NULL")
    op.alter_column(
        "split_tasks", "task_format", existing_type=sa.String(length=32), nullable=False
    )
    op.drop_index("ix_samples_split_task_start", table_name="samples")
    op.drop_column("samples", "end_time")
    op.drop_column("samples", "start_time")
