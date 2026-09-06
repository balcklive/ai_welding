# CLAUDE.md — backend/scripts/premise_validation/

集成 MLflow 与 Label Studio 的「待核实前提」验证脚本（一次性预研证据，**不污染正式 pytest 门禁**）。

## 文件

- `run_premise_validation.py`：本机可自动化项（无网络依赖，可离线）——
  - `check_ttl()`：minio SDK `presigned_get_object` 的 expires 上限（**1 秒~7 天**，>7 天抛 `ValueError`）+ `StorageClient.presign_get` 透传；
  - `check_fold()`：`torch_training.load_real_examples` 对含「熔池」标注样本的折叠结果（**当前误折为「缺陷」**）；
  - `check_mask_to_polygon()`：`skimage.find_contours` 栅格掩膜→polygon 顶点的近似度（规则形状 ~0.16% 偏差）；
  - `check_migration()`：`annotation_tasks` 加「LS 等待」状态列的 expand/contract 迁移（`ADD COLUMN ... NOT NULL DEFAULT` 单条即完成存量回填+新行默认+蓝绿兼容）。
- `probe_live.py`：真实 LS 探测（需能访问公网，默认 `http://182.61.59.135:8224`）——
  - `check_iframe()`：抓朗 `X-Frame-Options`/CSP `frame-ancestors`（**无 → iframe 嵌入可行**）；
  - `check_project_template()`：`GET /api/projects/<id>/` 判 BrushLabels/PolygonLabels（**需 `LABEL_STUDIO_API_KEY`**，无则输出需 key 的重跑命令）。
- `_ls_probe.py`：**服务器侧数据库探针**（确认项目模板的最权威手段）——`scp` 到服务器 → `docker cp` 进容器 → `docker exec label-studio python3 /tmp/_ls_probe.py`，直接读 `label_studio.sqlite3` 的 `project` 表打印 id=4 的 `label_config`（绕开 API token）。**实测确认 id=4 =「熔池语义分割 Segmentation」= BrushLabels 单类「熔池」（非 PolygonLabels）**。
- `probe_ls_sdk.py`：**只读 SDK 探测**（`label-studio-sdk` v2.1.1）——`dir(client)` 核对 `tasks/projects/annotations` 方法名 + `projects.list()` 拉项目 3/4/5 的 `label_config`（确认 4=PolygonLabels 单类熔池、5=TimeSeries `$csv`）。**验证了骨架 TODO "SDK 方法名以实际为准"**；`LABEL_STUDIO_PUBLIC_URL` 可覆盖默认 `http://182.61.59.135:8224`。read-only（不建 task）。
- `probe_ls_region.py`：**真实 region JSON 回读**——建 640×480 PNG 传 MinIO → 真实 SDK 建 task（项目3 box / 项目4 polygon）→ `annotations.create` 建真标注 → `tasks.get` 回读**精确 region result**（`type=rectanglelabels`/`polygonlabels`，label 在 `value.<plurallabel>[0]`，坐标 0-100% + `original_width/height`），然后删掉测试 task。**这修正了 `convert_region` 里猜测的 `rectangle`/`polygon` 类型串**。
- `e2e_ls_roundtrip.py`：**真实 e2e**（连真实 LS + 真实 MySQL + 真实 MinIO）——建 Job+AnnotationTask(ls_status=pending_ls)+Sample → `push_samples_to_ls` 真实 SDK 建 task → SDK 建真实标注 → **本机模拟 webhook** 调 `annotation_ls.handle_annotation_event` → 校验回写 `annotations`（category/kind/几何/annotator）+ 幂等（重发不重复落行）→ 清理 LS task + DB 行 + MinIO 对象。`BOX`（项目3 box）与 `POLY`（项目4 polygon）两条。**需 `LABEL_STUDIO_API_KEY` 且迁移已到 head；跑前先 `alembic upgrade head`**。
- `report.json` / `probe_live_report.json`：本脚本的 JSON 结果输出（git-ignored 与否见下）。

## 调用链

- 无外部调用方；手动 `cd backend && uv run python scripts/premise_validation/<script>.py`。
- 依赖：`backend/.venv`（`minio`/`skimage`），`uv run` 自带。

## 关键规则/坑

- **文件以 `check_*`/`probe_*` 命名，不匹配 pytest 的 `test_*` 收集规则**，故 `uv run pytest` 不会跑它们（避免污染推送门禁）；要跑就显式 `uv run python ...`。
- `run_premise_validation.py` 顶部 `sys.path.insert(0, <backend>)` 手动把 backend 加进 path（pytest 靠 `tests/__init__.py`，脚本需自理）。
- 结论文档：`docs/superpowers/specs/2026-09-05-integration-premise-verification.md`；改验证逻辑后同步该文档与两个 CLAUDE.md。
