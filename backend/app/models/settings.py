"""系统设置域实体：可配置选项（数据字典）。

对应 `docs/数据库设计.md` §3.26 `option_items`（新增表，见迁移 0015）。
设计要点：**单表 + group_key 分组**承载录入类可选项（厂家/焊机型号、焊接方法、
数据来源、产品信息、数据集任务类型），标注缺陷类别因已有 `label_categories`
（LS 集成 / 标注校验依赖）不并入本表，而是在该表上补 `active` + `sort_order`，
由 `app.services.settings` 统一成同一套"选项组"接口对外暴露。

停用语义（软删）：`active=False` 的项不再出现在录入下拉/候选里，但历史数据
（`data_records.machine` 等字符串列）不受影响，仍按原文本展示。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class OptionItem(SQLModel, table=True):
    """§3.26 option_items 可配置选项（按 group_key 分组的数据字典项）"""

    __tablename__ = "option_items"
    __table_args__ = (
        UniqueConstraint("group_key", "value", name="uq_option_items_group_value"),
    )

    id: int | None = Field(default=None, primary_key=True)
    #: 分组键，取值见 `app.services.settings.OPTION_GROUP_KEYS`（machine / weld_method / …）。
    group_key: str = Field(max_length=32, index=True)
    #: 选项值：即写入业务列的字符串（`data_records.machine`、`datasets.task` 等）。
    value: str = Field(max_length=128)
    sort_order: int = Field(default=0)
    #: 软删标记：False = 已停用（历史数据仍可展示，录入时不再出现）。
    active: bool = Field(default=True, index=True)
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
