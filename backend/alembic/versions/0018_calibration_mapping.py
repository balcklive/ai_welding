"""多模态统一坐标系：`data_versions` 增 `calibration`、`alignment_tasks` 增 `mapping`。

背景（见 `docs/多模态时间统一样本分段重构设计方案.md` §1.1/§3.1）：对齐任务此前**声称**对齐
但从没建立坐标映射——`alignment.py::_video_track` 硬编码 `aligned=True`，metadata 里只有视频
自身的 duration/fps/分辨率，**没有一个字段描述它与信号时间轴的关系**；下游三处（抽帧的
`ffmpeg -ss`、切片的 `video_frame_no`、前端播放器 seek）各自假装 `t_video ≡ t_signal`。
实测真实数据（`data/data/SP2026-06-000201/`）信号 182.0s、视频 180.9s，两轴可差 1.1s——
2 秒窗口下相当于 55% 窗宽，关键帧可能整个落在窗口外，且全程静默。

本次把标定与映射分两处落库，职责不同：

- `data_versions.calibration`（**源版本**上）：人工标定参数，`{video: {offset_seconds},
  seam_image: {roi: {x,y,w,h}}}`。NULL = 未标定。分段页只读它，不允许微调。
- `alignment_tasks.mapping`（对齐任务产出）：**可执行**的映射——统一轴 + 各模态 mapping
  （`linear` 视频 offset / `arc_length` 焊缝图片弧长 / `identity` 时序）。供分段任务按窗口
  换算视频帧与焊缝图像素。

为什么不复用 `alignment_tasks.tracks`：两者消费方不同。`tracks` 是**可用性展示**（前端的
轨道角标与 reason），`mapping` 是**算法输入**（分段 Job 的换算依据）。混在一起会让前端展示
结构绑架算法契约。

纯 expand 迁移，兼容蓝绿：两列均 nullable，老代码不读新列；新代码对 NULL 有兜底
（未标定 → `aligned=false` + reason，不阻断分段）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_versions", sa.Column("calibration", mysql.JSON(), nullable=True))
    op.add_column("alignment_tasks", sa.Column("mapping", mysql.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("alignment_tasks", "mapping")
    op.drop_column("data_versions", "calibration")
