"""Read-only probe of label-studio-sdk v2.1.1: method names + real label_config.

Verifies the TODO entry in integrations/labelstudio.py ("方法名以 label-studio-sdk v2
实际为准（落地时 dir(client) 核对）"). Connects to the real LS (public URL) with the PAT
already in .env. Does NOT create/delete any task — only reads.

Run: cd backend && uv run python scripts/premise_validation/probe_ls_sdk.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

# scripts/premise_validation -> parents[2] = backend/（app 包根，供 import app 用）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

# 让 settings 读到 e2e 用到的 public URL（settings 在 import 时读 .env）。
# .env 里 INTERNAL_URL/PUBLIC_URL 未设，故这里在 import app 前覆盖。
os.environ.setdefault("LABEL_STUDIO_MODE", "on")
os.environ.setdefault("LABEL_STUDIO_INTERNAL_URL", "http://182.61.59.135:8224")
os.environ.setdefault("LABEL_STUDIO_PUBLIC_URL", "http://182.61.59.135:8224")
os.environ.setdefault("LABEL_STUDIO_WEBHOOK_SECRET", "e2e-ls-secret")

from app.core.config import settings  # noqa: E402
from label_studio_sdk import LabelStudio  # noqa: E402


def d(obj) -> None:
    """Pretty-print a small object."""
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    print(f"mode={settings.label_studio_mode} internal={settings.label_studio_internal_url} "
          f"public={settings.label_studio_public_url} api_key_set={bool(settings.label_studio_api_key)}")
    client = LabelStudio(
        base_url=settings.label_studio_internal_url,
        api_key=settings.label_studio_api_key,
    )
    print("\n=== dir(client) ===")
    print([n for n in dir(client) if not n.startswith("_")])
    print("\n=== dir(client.tasks) ===")
    print([n for n in dir(client.tasks) if not n.startswith("_")])
    print("\n=== dir(client.projects) ===")
    print([n for n in dir(client.projects) if not n.startswith("_")])
    print("\n=== dir(client.annotations) ===")
    print([n for n in dir(client.annotations) if not n.startswith("_")])

    # 项目列表 & 各项目 label_config
    print("\n=== projects.list() ===")
    try:
        projects = client.projects.list()
        for p in projects:
            d({"id": p.id, "title": p.title, "label_config": getattr(p, "label_config", None)})
    except Exception as exc:  # noqa: BLE001
        print("projects.list failed:", exc)

    print("\n=== project 3/4/5 parsed_label_config (via projects.get) ===")
    for pid in (3, 4, 5):
        try:
            p = client.projects.get(pid)
            plc = getattr(p, "parsed_label_config", None) or getattr(p, "label_config", None)
            print(f"--- project {pid} ---")
            d(plc if isinstance(plc, dict) else plc)
        except Exception as exc:  # noqa: BLE001
            print(f"project {pid} get failed:", exc)

    print("\n=== existing tasks in project 3/4/5 (limit 2) ===")
    for pid in (3, 4, 5):
        try:
            tasks = client.tasks.list(project=pid)
            rows = list(tasks)[:2] if not isinstance(tasks, list) else tasks[:2]
            print(f"--- project {pid}: {len(rows)} preview(s) ---")
            for t in rows:
                d({"id": getattr(t, "id", None), "data": getattr(t, "data", None),
                   "annotations": getattr(t, "annotations", None)})
        except Exception as exc:  # noqa: BLE001
            print(f"tasks.list project {pid} failed:", exc)


if __name__ == "__main__":
    main()
