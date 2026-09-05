"""临时探针：直接读 LS 容器内 sqlite 的 project 表，确认 id=4 的 label_config 工具类型。

只回传工具标签与模板片段（无账号/无 secret）。用 scp 到服务器 /tmp 后 docker exec 执行。
"""

import re
import sqlite3

c = sqlite3.connect("/label-studio/data/label_studio.sqlite3")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
print("RELATED TABLES:", [t for t in tables if "project" in t.lower() or "label" in t.lower()] or tables)

# 定位 project 表（常见名：project / projects）
pt = next((t for t in tables if t.lower() in ("project", "projects", "label_studio_project")), None)
if pt is None:
    print("NO_PROJECT_TABLE; all tables:", tables)
    raise SystemExit(0)

cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % pt)]
print("PROJECT COLS:", cols)
id_cols = [col for col in cols if col.lower() in ("id",)]
label_col = next((col for col in cols if col.lower() in ("label_config", "label_config_json", "labels")), None)
title_col = next((col for col in cols if col.lower() in ("title", "name")), None)
sel_cols = [x for x in (id_cols[0] if id_cols else "id", title_col, label_col) if x]
if label_col is None:
    print("NO_LABEL_COL; cols:", cols)
    raise SystemExit(0)

sql = "SELECT %s FROM %s WHERE %s = 4" % (",".join(sel_cols), pt, id_cols[0])
rows = c.execute(sql).fetchall()
if not rows:
    print("PROJECT 4 NOT FOUND; run: SELECT id FROM %s" % pt)
    raise SystemExit(0)

for r in rows:
    lc = r[-1] or ""
    tools = sorted(set(re.findall(r"<([A-Za-z]+Labels?)", lc)))
    print("PROJECT 4 title=%s" % (r[1] if len(r) > 1 else "?"))
    print("PROJECT 4 tools:", tools)
    print("HAS_BrushLabels:", "<BrushLabels" in lc, "HAS_PolygonLabels:", "<PolygonLabels" in lc)
    print("label_config sample:", re.sub(r"\s+", " ", lc)[:600])
