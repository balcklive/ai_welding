"""真实服务探测脚本（前提 #5 iframe、#6 项目4模板）。

面向能访问 LS 的公网地址（默认 `http://182.61.59.135:8224`，可用环境变量覆盖）运行：
  cd backend && uv run python scripts/premise_validation/probe_live.py

前提 #5（iframe embed）：抓 LS 根路径/登录/项目/任意路径响应头的
  `X-Frame-Options` 与 `Content-Security-Policy(-Report-Only)` 的 `frame-ancestors`，
  据此判定平台能否 iframe 嵌入 LS。
前提 #6（项目4模板）：调 `GET /api/projects/4/`（Legacy token 头 `Authorization: Token <key>`），
  读 `label_config` 判定 id=4 是 BrushLabels（掩膜）还是 PolygonLabels（多边形顶点）。
  无 key 时输出「需提供 LABEL_STUDIO_API_KEY」，仅确认 `/api/projects/` 需认证。

输出：stdout 汇总 + 同目录 probe_live_report.json
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

BASE = os.environ.get("LABEL_STUDIO_PUBLIC_URL", "http://182.61.59.135:8224").rstrip("/")
API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")  # 仅服务器 .env 有；本机通常为空
PROJECT_ID = os.environ.get("LS_PROJECT_ID", "4")


def http_fetch(url: str, headers: dict | None = None, timeout: int = 10):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "url": url,
                "status": resp.status,
                "headers": dict((k.lower(), v) for k, v in resp.headers.items()),
                "body_prefix": resp.read(512).decode("utf-8", "replace")[:200],
            }
    except urllib.error.HTTPError as e:
        return {
            "url": url,
            "status": e.code,
            "headers": dict((k.lower(), v) for k, v in e.headers.items()),
            "body_prefix": e.read(200).decode("utf-8", "replace")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "status": None, "error": f"{type(exc).__name__}: {exc}"}


def check_iframe():
    """判定 LS 是否被 iframe 嵌入：无 X-Frame-Options 且 CSP 无 frame-ancestors 即可嵌。"""
    paths = ["/", "/user/login/", "/project/", "/api/projects/"]
    pages = [http_fetch(BASE + p) for p in paths]
    rows = []
    for page in pages:
        headers = page.get("headers", {})
        xfo = headers.get("x-frame-options")
        csp = (
            headers.get("content-security-policy", "")
            + " || "
            + headers.get("content-security-policy-report-only", "")
        )
        has_ancestors = "frame-ancestors" in csp.lower()
        # X-Frame-Options: DENY/SAMEORIGIN 会禁跨域 iframe；frame-ancestors 若含 'self' 也禁跨域
        frame_block = bool(xfo) or has_ancestors
        is_report_only = "content-security-policy-report-only" in headers
        rows.append({
            "path": page["url"].replace(BASE, ""),
            "status": page.get("status"),
            "x_frame_options": xfo,
            "csp": ("(见下)" if csp else None),
            "has_frame_ancestors": has_ancestors,
            "csp_is_report_only": is_report_only,
            "iframe_blocked": frame_block,
        })
    # 结论：只要无 XFO 且无 frame-ancestors → 可嵌入（blocked=False 即安全）
    any_blocked = any(r["iframe_blocked"] for r in rows)
    verdict = (
        "可行（无 X-Frame-Options，CSP 为 Report-Only 且无 frame-ancestors → 不限制跨域 iframe 嵌入）"
        if not any_blocked
        else "受限（存在禁止/限制嵌入响应头）"
    )
    lines = ["iframe embed 判定逐路径："]
    for r in rows:
        lines.append(
            f"  {r['path']} status={r['status']} XFO={r['x_frame_options']} "
            f"frame-ancestors={r['has_frame_ancestors']} (CSP report-only={r['csp_is_report_only']}) "
            f"-> {'BLOCK' if r['iframe_blocked'] else 'allow'}"
        )
    lines.append(f"结论: {verdict}")
    status = "PASS" if not any_blocked else "WARN"
    return status, "\n".join(lines), {"rows": rows, "verdict": verdict}


def check_project_template():
    """用 legacy token 查项目 id，读 label_config，判定 id=4 是 BrushLabels 还是 PolygonLabels。"""
    if not API_KEY:
        return (
            "INFO",
            "未提供 LABEL_STUDIO_API_KEY（该值在服务器 .env）。"
            "仅能确认 `/api/projects/` 需要认证（见 iframe 探测 status=401）；"
            "需在能读取服务器 .env 的环境重跑 `LABEL_STUDIO_API_KEY=... python probe_live.py` 才能拿到 id=4 的 label_config。",
            {"needs_api_key": True},
        )
    headers = {"Authorization": f"Token {API_KEY}"}
    raw = http_fetch(f"{BASE}/api/projects/", headers=headers)
    if raw.get("status") != 200:
        return (
            "WARN",
            f"GET /api/projects/ 返回 {raw.get('status')}: {raw.get('body_prefix')}",
            {"status": raw.get("status")},
        )
    projects = json.loads(raw["body_prefix"] if isinstance(raw.get("body_prefix"), str) else "[]")
    # body_prefix 被截断到 200 字符，可能不是完整 JSON；尝试重新完整解析
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/projects/", headers=headers), timeout=10) as resp:
            projects = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return "WARN", f"无法完整解析项目列表: {exc}", {"needs_api_key": True}

    by_id = {str(p.get("id")): p for p in projects}
    proj = by_id.get(PROJECT_ID)
    if proj is None:
        ids = [str(p.get("id")) for p in projects]
        return (
            "WARN",
            f"未找到项目 id={PROJECT_ID}（现有项目 id: {ids}）。",
            {"known_project_ids": ids},
        )
    label_config = proj.get("label_config", "") or ""
    is_brush = "<BrushLabels" in label_config
    is_polygon = "<PolygonLabels" in label_config
    tool_kind = "BrushLabels(掩膜)" if is_brush else "PolygonLabels(多边形)" if is_polygon else "未知/其它"
    lines = [
        f"项目 {PROJECT_ID}: name={proj.get('title')} tool={tool_kind}",
        f"label_config 片段: {label_config[:200]}",
    ]
    if is_brush:
        lines.append("→ 当前是 BrushLabels：平台视频帧用 PolygonLabels(polygon 顶点)，二者不一致。需二选一："
                     "LS 改 PolygonLabels 模板 / 接受掩膜回写→轮廓或 rle 存储（见掩膜→轮廓可行性）。")
        status = "WARN"
    elif is_polygon:
        lines.append("→ 当前已是 PolygonLabels：与平台 polygon 顶点模型一致。")
        status = "PASS"
    else:
        lines.append("→ 无法从 label_config 判定；需人工核对。")
        status = "WARN"
    return status, "\n".join(lines), {"project": {"id": PROJECT_ID, "tool": tool_kind, "label_config": label_config}}


def main():
    results = [
        _wrap("iframe embed 响应头", check_iframe),
        _wrap("LS 项目4 真实模板", check_project_template),
    ]
    print("=" * 70)
    print("真实服务探测结果（需能访问 LS 公网地址）")
    print("=" * 70)
    for r in results:
        print(f"\n### {r['name']}  [{r['status']}]")
        print(r["evidence"])
    print("\n" + "=" * 70)
    out = pathlib.Path(__file__).resolve().parent / "probe_live_report.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"probe_live_report.json -> {out}")
    return 0


def _wrap(name, fn):
    try:
        status, evidence, detail = fn()
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "status": "ERROR", "evidence": f"异常: {type(exc).__name__}: {exc}", "detail": {}}
    return {"name": name, "status": status, "evidence": evidence, "detail": detail}


if __name__ == "__main__":
    raise SystemExit(main())
