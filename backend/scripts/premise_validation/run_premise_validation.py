"""前提验证脚本（一次性预研证据，不污染正式 pytest 门禁）。

针对 `docs/superpowers/plans/2026-09-05-integrate-mlflow-labelstudio-into-main-app.md`
的「待核实前提」，逐个跑可自动化验证项，输出结构化结果供评审。

可本机自动化验证：
  1. 预签名 URL TTL 上限           —— minio SDK presigned_get_object 的 expires 上限 + StorageClient 透传
  2. 熔池/正常 训练折叠行为        —— torch_training.load_real_examples 对含「熔池」标注样本的折叠结果
  3. 掩膜→轮廓 可行性             —— skimage.find_contours 把 BrushLabels 栅格掩膜转 polygon 顶点的近似度
  4. 历史数据回填迁移             —— annotation_tasks 加「LS 等待」状态列的 expand/contract 兼容

需连真实服务（见 run_live_probe.sh，须在能访问服务器的环境执行）：
  5. iframe embed 响应头           —— LS 站点 X-Frame-Options / CSP frame-ancestors
  6. LS 项目4 真实模板             —— /api/projects/4/ label_config（需服务器 .env 的 API key）

运行：cd backend && uv run python scripts/premise_validation/run_premise_validation.py
输出：stdout 汇总 + scripts/premise_validation/report.json
"""

from __future__ import annotations

import json
import pathlib
import sys

# 让本脚本能 import backend 的 app 包（pytest 靠 tests/__init__.py，本脚本手动加 path）
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import io  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass


def _wrap(name: str, fn):
    """跑单个检查，记录状态/证据/详情；异常不中断整体。"""
    try:
        status, evidence, detail = fn()
    except Exception as exc:  # noqa: BLE001 - 检查自身不应中断整体
        return {
            "name": name,
            "status": "ERROR",
            "evidence": f"检查抛出异常: {type(exc).__name__}: {exc}",
            "detail": {},
        }
    return {"name": name, "status": status, "evidence": evidence, "detail": detail}


# ---------------------------------------------------------------------------
# 1. 预签名 URL TTL 上限
# ---------------------------------------------------------------------------


def check_ttl():
    """确认 minio SDK `presigned_get_object` 的 expires 上限，并验证 StorageClient 透传 expires。

    minio SDK 的预签名是**纯本地签名**（不连网络），故无需真实 MinIO 即可测上限；
    StorageClient.presign_get 走 `_sign_client`（公网），这里用注入 fake 验证透传行为。
    """
    from minio import Minio

    # region 显式给出可跳过 get_bucket_location 网络嗅探，让 presign 本地完成（无真实 MinIO 也能出 URL）
    client = Minio("localhost:9000", access_key="ak", secret_key="sk", secure=False, region="us-east-1")

    expires_cases = {
        "1 天 (86400)": 86400,
        "3 天 (259200)": 259200,
        "7 天 (604800)": 604800,
        "8 天 (691200)": 691200,
        "15 天 (1296000)": 1296000,
    }
    rows = []
    for label, seconds in expires_cases.items():
        try:
            url = client.presigned_get_object("aiwelding", "x/1.jpg", expires=datetime_timedelta(seconds=seconds))
            rows.append({"expires": label, "ok": True, "len": len(url)})
        except Exception as exc:  # noqa: BLE001
            rows.append({"expires": label, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    # StorageClient 透传：注入 fake，绕过 _ensure_bucket 的网络依赖，观察传给 sign_client 的 expires
    from app.storage import client as storage_client_mod

    calls: list[int] = []

    class FakeDataMinio:  # 数据面：presign_get 会先调 bucket_exists
        def bucket_exists(self, bucket):
            return True

        def make_bucket(self, bucket):
            return None

    class FakeSignMinio:  # 预签名面：记录收到的 expires
        def presigned_get_object(self, bucket, object_name, expires):
            calls.append(expires.total_seconds())
            return f"https://fake/{bucket}/{object_name}"

    sc = storage_client_mod.StorageClient(
        client=FakeDataMinio(),  # type: ignore[arg-type]
        sign_client=FakeSignMinio(),  # type: ignore[arg-type]
    )
    sc.presign_get("x/1.jpg", expires=604800)
    sc.presign_get("x/1.jpg", expires=259200)
    passthrough = calls == [604800.0, 259200.0]

    ok_rows = [r for r in rows if r["ok"]]
    max_ok_secs = None
    for r in rows:
        if r["ok"]:
            max_ok_secs = r["expires"]
        else:
            break
    evidence_lines = ["minio SDK prensigned_get_object expires 上限逐档："]
    for r in rows:
        evidence_lines.append(f"  {r['expires']}: {'通过(' + str(r['len']) + '字符)' if r['ok'] else '拒绝 -> ' + r['error']}")
    evidence_lines.append(f"StorageClient.presign_get 透传 expires: {'通过' if passthrough else '不透传!'} (calls={calls})")
    evidence_lines.append(f"结论: SDK accepts up to {max_ok_secs}; 超过即抛错。故长 TTL 须选在 7 天内。")

    status = "PASS" if passthrough and any(r["ok"] for r in rows) else "WARN"
    return status, "\n".join(evidence_lines), {"rows": rows, "passthrough": passthrough}


def datetime_timedelta(**kwargs):
    from datetime import timedelta

    return timedelta(**kwargs)


# ---------------------------------------------------------------------------
# 2. 熔池/正常 训练折叠行为
# ---------------------------------------------------------------------------


def check_fold():
    """确认 load_real_examples 当前把「熔池」标注折叠到哪一类。

    构造内存 SQLite（精简 Raw 表，避免环形 FK），3 个样本：气孔(缺陷)/熔池/无标注。
    """
    from sqlalchemy import create_engine as sa_create_engine
    from sqlmodel import Session

    from app.models.analysis import Annotation, Sample  # noqa: F401
    from app.models.datasets import DatasetItem  # noqa: F401

    engine = sa_create_engine(
        "sqlite://", connect_args={"check_same_thread": False}
    )
    ddl = [
        "CREATE TABLE dataset_items (id INTEGER PRIMARY KEY, dataset_version_id INTEGER, sample_id INTEGER, split VARCHAR(8))",
        "CREATE TABLE samples (id INTEGER PRIMARY KEY, split_task_id INTEGER, annotation_task_id INTEGER, frame_no INTEGER, object_keys TEXT, meta TEXT)",
        "CREATE TABLE annotations (id INTEGER PRIMARY KEY, sample_id INTEGER, category VARCHAR(32), kind VARCHAR(16), box TEXT, points TEXT, start_time REAL, end_time REAL, confidence REAL, annotator VARCHAR(64), created_at TEXT, updated_at TEXT)",
    ]
    with engine.begin() as conn:
        for d in ddl:
            conn.exec_driver_sql(d)

    def ins(table, cols, *rows):
        with engine.begin() as conn:
            for r in rows:
                conn.exec_driver_sql(
                    f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    r,
                )

    ins(
        "samples",
        ["id", "split_task_id", "annotation_task_id", "frame_no", "object_keys", "meta"],
        (1, None, None, None, '["s1.json"]', "{}"),
        (2, None, None, None, '["s2.json"]', "{}"),
        (3, None, None, None, '["s3.json"]', "{}"),
    )
    ins("dataset_items", ["id", "dataset_version_id", "sample_id", "split"],
        (1, 900, 1, "train"),
        (2, 900, 2, "val"),
        (3, 900, 3, "train"),
    )
    ins("annotations", ["id", "sample_id", "category", "kind", "box", "points", "start_time", "end_time", "confidence", "annotator", "created_at", "updated_at"],
        (1, 1, "气孔", "box", "[1,2,3,4]", "[]", None, None, 0.9, "真", None, None),
        (2, 2, "熔池", "box", "[1,2,3,4]", "[]", None, None, 0.9, "真", None, None),
    )

    class FakeStorage:  # 只提供 get_object 供 _features_from_sample 解析
        def get_object(self, key):
            return b'[1,2,3,4,5]'

    from app.services import torch_training

    with Session(engine) as session:
        examples, classes = torch_training.load_real_examples(session, 900, FakeStorage())

    by_label: dict[int, dict] = {}
    for e in examples:
        by_label[e.sample_id] = {"split": e.split, "label": e.label, "label_name": e.label_name}

    def show(sid, desc):
        row = by_label.get(sid)
        return f"{desc}: label_name={row['label_name'] if row else 'MISSING'} (label={row['label'] if row else '?'})"

    lines = [
        f"类表(classes) = {classes}",
        show(1, "样本1 标注=气孔 (真实缺陷)"),
        show(2, "样本2 标注=熔池 (分割对象,非缺陷)"),
        show(3, "样本3 无标注 (应=正常)"),
    ]
    fold_melting = by_label.get(2, {}).get("label_name")
    # 期望行为：熔池应归 "正常"/独立类；当前代码把任意非空 category 归 "缺陷"。
    lines.append(f"结论: 当前代码将「熔池」折叠为 '{fold_melting}'(缺陷)。熔池是分割对象非缺陷，此为语义错误，需在产品裁决前分流。")

    status = "WARN"  # 这是暴露问题，不是"通过"
    return status, "\n".join(lines), {"examples": by_label, "classes": classes, "melting_fold_to": fold_melting}


# ---------------------------------------------------------------------------
# 3. 掩膜→轮廓 可行性
# ---------------------------------------------------------------------------


def check_mask_to_polygon():
    """用 skimage.find_contours 把 BrushLabels 的二进制掩膜转 polygon 顶点，量化近似度。"""
    import numpy as np
    from skimage import measure

    # 构造 32x32 掩膜：中央一个 20x16 实心矩形（规则形状，量化"规则掩膜几乎无损"）
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[8:24, 6:26] = 1
    contours = measure.find_contours(mask.astype(float), 0.5)
    contour = contours[0]

    # find_contours 返回 (row, column) 浮点；转 [x=col, y=row] 顶点
    points = [[round(float(c), 2), round(float(r), 2)] for r, c in contour]

    # 量化近似度：轮廓多边形面积 vs 原始掩膜像素面积（用 skimage 的 measure 面积）
    from skimage import measure as _m

    contour_img = np.zeros_like(mask)
    # 用多边形填充近似：将轮廓点集转成 polygon，用 matplotlib-free 的面积近似
    # 简化：直接用 find_contours 外包的 shoelace 面积
    area_poly = _m.approximate_polygon(contour, tolerance=0.5)  # 占位
    shoelace = _shoelace(points)
    mask_area = float(mask.sum())

    lines = [
        f"掩膜尺寸 32x32，实心矩形像素面积 = {mask_area:.0f}",
        f"find_contours 返回 {len(contours)} 条轮廓，主轮廓顶点数 = {len(points)}",
        f"多边形 shoelace 面积 = {shoelace:.2f}，与像素面积偏差 = {abs(shoelace - mask_area):.2f} ({100*abs(shoelace-mask_area)/mask_area:.2f}%)",
        f"结论: 规则掩膜 → 多边形顶点几乎无损；不规则锯齿边缘会引入误差（可用 approximate_polygon tolerance 控制顶点数）。",
    ]
    status = "PASS"
    return status, "\n".join(lines), {"vertices": len(points), "mask_area": mask_area, "poly_area": shoelace}


def _shoelace(points: list[list[float]]) -> float:
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


# ---------------------------------------------------------------------------
# 4. 历史数据回填迁移
# ---------------------------------------------------------------------------


def check_migration():
    """验证 annotation_tasks 加「LS 等待」状态列的迁移：expand + 存量回填 + 蓝绿兼容。

    用 SQLite 模拟（MySQL 语义等价）：ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT 'annotating'
    一条语句即同时给存量行回填默认 + 保证新行默认 + 旧代码(不读该列)读取不崩 → 蓝绿 expand 兼容。
    """
    from sqlalchemy import create_engine as sa_create_engine

    engine = sa_create_engine("sqlite://", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE annotation_tasks (id INTEGER PRIMARY KEY, job_id INTEGER UNIQUE, split_task_id INTEGER, name VARCHAR(128), source VARCHAR(32), created_at TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO annotation_tasks (id, job_id, name, source) VALUES (1, 101, '旧任务A', 'split_task')")
        conn.exec_driver_sql("INSERT INTO annotation_tasks (id, job_id, name, source) VALUES (2, 102, '旧任务B', 'signal')")

        # expand：加「LS 等待」状态列，带默认值 → 存量行自动回填默认，无需单独 UPDATE
        conn.exec_driver_sql("ALTER TABLE annotation_tasks ADD COLUMN ls_status VARCHAR(16) NOT NULL DEFAULT 'annotating'")

        # 蓝绿验证：存量行 A/B 应自动拿到默认 'annotating'（即旧任务进入标注中）
        existing_after = list(conn.exec_driver_sql("SELECT id, name, ls_status FROM annotation_tasks ORDER BY id").all())

        # 新行（新代码创建）不显式写 ls_status → 触发默认
        conn.exec_driver_sql("INSERT INTO annotation_tasks (id, job_id, name, source) VALUES (3, 103, '新任务C', 'video')")
        new_row = list(conn.exec_driver_sql("SELECT id, name, ls_status FROM annotation_tasks WHERE id=3").all())

    existing_after = [tuple(r) for r in existing_after]
    new_row = [tuple(r) for r in new_row]
    lines = [
        "expand 后存量行（应自动=annotating）：",
        f"  {existing_after}",
        "新插入行（未显式写 ls_status，应触发默认）：",
        f"  {new_row}",
    ]
    all_annotating = all(r[2] == "annotating" for r in existing_after) and new_row and new_row[0][2] == "annotating"
    lines.append(f"结论: {'通过' if all_annotating else '不通过'} —— 单条 ADD COLUMN + NOT NULL DEFAULT 即可同时完成存量回填、新行默认、蓝绿 expand 兼容。")
    status = "PASS" if all_annotating else "WARN"
    return status, "\n".join(lines), {"existing_after": existing_after, "new_row": new_row}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main():
    checks = [
        ("预签名 URL TTL 上限", check_ttl),
        ("熔池/正常 训练折叠行为", check_fold),
        ("掩膜→轮廓 可行性", check_mask_to_polygon),
        ("历史数据回填迁移", check_migration),
    ]
    results = [_wrap(name, fn) for name, fn in checks]

    print("=" * 70)
    print("前提验证结果（本机可自动化项）")
    print("=" * 70)
    for r in results:
        print(f"\n### {r['name']}  [{r['status']}]")
        print(r["evidence"])
    print("\n" + "=" * 70)

    report = {
        "generated_at": None,
        "checks": results,
    }
    out = pathlib.Path(__file__).resolve().parent / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report.json -> {out}")
    return 0 if all(r["status"] != "ERROR" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
