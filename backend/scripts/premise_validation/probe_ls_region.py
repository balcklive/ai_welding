"""Learn the exact LS region JSON for RectangleLabels / PolygonLabels — real round-trip.

Creates a real 640x480 PNG in MinIO, creates a real LS task in project 3 (box) and
project 4 (polygon), adds a real annotation via the SDK, reads it back, and prints the
exact result region JSON. Cleans up the LS tasks afterwards (no DB rows are written here).

Run: cd backend && uv run python scripts/premise_validation/probe_ls_region.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

os.environ.setdefault("LABEL_STUDIO_MODE", "on")
os.environ.setdefault("LABEL_STUDIO_INTERNAL_URL", "http://182.61.59.135:8224")
os.environ.setdefault("LABEL_STUDIO_PUBLIC_URL", "http://182.61.59.135:8224")
os.environ.setdefault("LABEL_STUDIO_WEBHOOK_SECRET", "e2e-ls-secret")

from app.core.config import settings  # noqa: E402
from app import storage  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
import io  # noqa: E402

from label_studio_sdk import LabelStudio  # noqa: E402


def d(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def make_png(w: int = 640, h: int = 480) -> bytes:
    img = Image.new("RGB", (w, h), (40, 44, 52))
    draw = ImageDraw.Draw(img)
    draw.rectangle([140, 120, 360, 300], fill=(60, 140, 90))
    draw.ellipse([440, 60, 560, 180], fill=(90, 90, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload_presign(stow, key: str, blob: bytes, ctype: str) -> str:
    stow.upload_stream(key, io.BytesIO(blob), len(blob), ctype)
    return stow.presign_get(key)


def main() -> None:
    stow = storage.get_storage()
    client = LabelStudio(base_url=settings.label_studio_internal_url, api_key=settings.label_studio_api_key)
    created_tasks: list[int] = []
    try:
        blob = make_png()
        # 上传真实对象并取预签名 URL（公网端点，LS 服务端可拉取）
        image_url = upload_presign(stow, "e2e/ls_region_probe.png", blob, "image/png")
        print("image_url:", image_url[:120], "...")

        # ── Project 3: RectangleLabels (detection / box) ──
        task3 = client.tasks.create(project=3, data={"image": image_url})
        created_tasks.append(int(task3.id))
        print(f"\n[P3] created task id={task3.id}")
        # 新增一条 rectanglelabels 标注（真实写入 LS）
        ann = client.annotations.create(
            int(task3.id),
            result=[{
                "id": "p3-region-1",
                "type": "rectanglelabels",
                "from_name": "label",
                "to_name": "image",
                "original_width": 640,
                "original_height": 480,
                "image_rotation": 0,
                "value": {"x": 12.5, "y": 20.0, "width": 30.0, "height": 25.0, "rectanglelabels": ["气孔"]},
            }],
            task=int(task3.id),
            completed_by=1,
        )
        print("[P3] annotation created id=", getattr(ann, "id", None))
        print("[P3] annotation result (read back via task.get):")
        t3 = client.tasks.get(int(task3.id))
        d(getattr(t3, "annotations", None))

        # ── Project 4: PolygonLabels (熔池分割 / polygon) ──
        task4 = client.tasks.create(project=4, data={"image": image_url})
        created_tasks.append(int(task4.id))
        print(f"\n[P4] created task id={task4.id}")
        client.annotations.create(
            int(task4.id),
            result=[{
                "id": "p4-region-1",
                "type": "polygonlabels",
                "from_name": "label",
                "to_name": "image",
                "original_width": 640,
                "original_height": 480,
                "image_rotation": 0,
                "value": {"points": [[10.0, 20.0], [40.0, 20.0], [40.0, 50.0], [10.0, 50.0]], "polygonlabels": ["熔池"], "closed": True},
            }],
            task=int(task4.id),
            completed_by=1,
        )
        print("[P4] annotation result (read back via task.get):")
        t4 = client.tasks.get(int(task4.id))
        d(getattr(t4, "annotations", None))
    finally:
        # 清理 LS task（不写库，故无 DB 行需清理）
        for tid in reversed(created_tasks):
            try:
                client.tasks.delete(tid)
                print(f"deleted LS task id={tid}")
            except Exception as exc:  # noqa: BLE001
                print(f"failed to delete LS task {tid}: {exc}")


if __name__ == "__main__":
    main()
