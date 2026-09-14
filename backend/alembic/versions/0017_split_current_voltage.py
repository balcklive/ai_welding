"""D7 电流/电压拆列：`data_records` 增 `current_a` / `voltage_v` 并回填历史值。

背景：`current_voltage` 是一个 `VARCHAR(32)`，把两个物理量塞在一起（实测存量值有
`'180 A / 22 V'`、`'180A/22V'`、`'250A / 25V'` 与空串）。T4.2 要求按建模所需完整集做必填与
**量程**校验（电流 1–2000 A、电压 1–200 V），字符串形式无法可靠校验，故拆成两个 `NUMERIC(8,2)`。

回填规则（按 `current_voltage` 解析，覆盖实测形态）：

- `180 A / 22 V`、`180A/22V`、`250A / 25V` → current=180/250、voltage=22/25；
- `180/22` → current=180、voltage=22；
- `180` → 只解析出电流；
- 空串 / `NULL` / 解析失败 → 两列都留 NULL，**旧列原样保留**（过渡期读取时回落解析旧列）。

**旧列不删**：读取侧（`record_payload`）过渡期继续输出旧值。纯 expand + 数据回填，兼容蓝绿：
老代码不读新列。

R6 补的两条：

- 解析失败的行**不再静默跳过**，逐行写 `alembic` 日志（迁移后可直接 grep 出来补录）；
- `downgrade` 先把新列**拼回旧列**再删列——迁移后新登记的数据旧列是 NULL（写入只写新列），
  不反填就会在回滚时整列丢值。
"""
import logging
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

log = logging.getLogger("alembic.runtime.migration")

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels = None
depends_on = None

#: 形如 `180 A / 22 V`、`180A/22V`、`180/22`、`180`；只认前两个数字（电流在前）。
_PAIR_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[aA]?\s*(?:/\s*(\d+(?:\.\d+)?)\s*[vV]?\s*)?$")


def _parse_current_voltage(value: str | None) -> tuple[float | None, float | None]:
    """`current_voltage` → `(current_a, voltage_v)`；解析不出的部分返回 None。"""
    if not value:
        return None, None
    match = _PAIR_PATTERN.match(str(value))
    if not match:
        return None, None
    current = float(match.group(1))
    voltage = float(match.group(2)) if match.group(2) else None
    return current, voltage


def upgrade() -> None:
    op.add_column("data_records", sa.Column("current_a", mysql.NUMERIC(8, 2), nullable=True))
    op.add_column("data_records", sa.Column("voltage_v", mysql.NUMERIC(8, 2), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, current_voltage FROM data_records WHERE current_voltage IS NOT NULL")
    ).fetchall()
    failed: list[int] = []
    filled = 0
    # 空串不算"解析失败"——它本来就没有值（实测存量里有），不该刷屏
    for record_id, raw in rows:
        if raw is None or str(raw).strip() == "":
            continue
        current, voltage = _parse_current_voltage(raw)
        if current is None and voltage is None:
            failed.append(record_id)
            continue
        connection.execute(
            sa.text(
                "UPDATE data_records SET current_a = :current, voltage_v = :voltage WHERE id = :id"
            ),
            {"current": current, "voltage": voltage, "id": record_id},
        )
        filled += 1
    log.info("0017 电流电压拆列：回填 %d 行", filled)
    if failed:
        for record_id in failed:
            log.warning(
                "0017 电流电压拆列：data_records.id=%s 的 current_voltage 解析失败，两列留 NULL，请人工补录",
                record_id,
            )
        log.warning("0017 电流电压拆列：共 %d 行解析失败（id 见上）", len(failed))


def downgrade() -> None:
    """回滚前把新列拼回旧列：迁移后登记的记录旧列是 NULL（只写新列），不反填就整列丢值。

    逐行 Python 拼串而不用 SQL 函数——`CONCAT` / `CAST(… AS CHAR)` 是 MySQL 方言，迁移要能在
    SQLite 上跑通（测试库）。
    """
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, current_a, voltage_v FROM data_records "
            "WHERE current_voltage IS NULL AND (current_a IS NOT NULL OR voltage_v IS NOT NULL)"
        )
    ).fetchall()
    for record_id, current, voltage in rows:
        connection.execute(
            sa.text("UPDATE data_records SET current_voltage = :legacy WHERE id = :id"),
            {"legacy": _format_legacy(current, voltage), "id": record_id},
        )
    if rows:
        log.info("0017 回滚：把 %d 行新列拼回 current_voltage", len(rows))
    op.drop_column("data_records", "voltage_v")
    op.drop_column("data_records", "current_a")


def _format_legacy(current: float | None, voltage: float | None) -> str:
    """`(current_a, voltage_v)` → `current_voltage` 的字符串形态（与解析规则互为逆运算）。

    只有电压没有电流时拼成 `? A / 22 V`：解析规则**以第一个数字当电流**，编个 0 会读成"0 A"，
    宁可让回滚后这一格解析不出（该行已记日志）也别写进一个假值。
    """
    def _fmt(value: float | None) -> str:
        if value is None:
            return "-"
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)

    if current is None:
        return f"? A / {_fmt(voltage)} V"
    if voltage is None:
        return f"{_fmt(current)} A"
    return f"{_fmt(current)} A / {_fmt(voltage)} V"
