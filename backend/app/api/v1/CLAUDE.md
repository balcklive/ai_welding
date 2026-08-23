# CLAUDE.md — backend/app/api/v1/

v1 版路由。`/api/v1` 前缀由 `main.py` 挂载时统一添加，各域 router 自身不带前缀。

## 脚本

- `__init__.py`：空包。
- `router.py`：`api_router = APIRouter()`，`include_router` 聚合全部 9 个域 router。新增域时在此追加 import + include_router。
- `auth.py`：**Task 5 已实现**。router `prefix="/auth"`（完整路径 `/api/v1/auth/login`、`/api/v1/auth/me`）。`POST /login` body `{username,password}` → 查 `users` 表校验 → `ok({access_token, token_type:"bearer", user:{id,username,display_name,role,avatar}})`；用户名/密码错 → `err(40100, "用户名或密码错误", status=401)`。**防时序用户枚举（Task 5 修复）**：用户不存在时仍对模块级 `_DUMMY_HASH`（argon2，导入时算一次）跑一次 `verify_password`，使未知/已知用户名两条路径耗时相当；返回体一致。`GET /me`（依赖 `api.deps.get_current_user`）→ `ok(user)`。`user_payload(user)` 暴露对外字段。
- `dashboard.py`：**Task 8 已实现**。router `prefix="/dashboard"`（完整路径 `/api/v1/dashboard/*`），
  **router 级 `dependencies=[Depends(get_current_user)]` 统一要求登录**。四个端点
  `GET /stats`（统计卡）/ `GET /attributes`（属性面板）/ `GET /distributions`（分布图）/
  `GET /projects`（数据项目卡片）→ `ok(...)`。聚合逻辑在 `app.services.dashboard`。
- `welds.py`：占位（`# filled in Task 10`）。焊缝数据核心 CRUD。
- `analysis.py`：占位（`# filled in Task 11`）。分析 + DSP 真实实现。
- `datasets.py`：占位（`# filled in Task 15`）。数据集 + 构建任务。
- `models.py`：占位（`# filled in Task 16`）。模型 + 训练/测试/推理。
- `files.py`：**Task 9 已实现**。router `prefix="/files"`（完整路径 `/api/v1/files/*`），
  **router 级 `dependencies=[Depends(get_current_user)]` 统一要求登录**。三个端点：
  - `POST /upload`（multipart `file`，小文件 <100MB 后端代理）：object_key 前缀
    固定 `uploads/{uuid}`，流式读取 + 字节计数封顶（`MAX_PROXY_UPLOAD_SIZE`，
    Content-Length 有则先快速拒绝），`upload_stream` 后 `presign_get` 返回
    `ok({object_key, url})`。超限 → `err(40000, ..., status=400)`。
  - `POST /presign-upload`（body `{size, content_type, prefix, filename?}`）：
    校验 `0 < size ≤ 2GB`（`MAX_PRESIGN_UPLOAD_SIZE`），调 `presign_put` 返回
    `ok({object_key, upload_url})`；空 prefix（normalize_key 抛 ValueError）→ 400。
  - `GET /{object_key:path}/url?expires=`：object_key 含 `/`（如 `uploads/<uuid>/x.mp4`），
    用 `:path` 捕获；`expires` 默认 3600、上限 86400（`MAX_PRESIGN_GET_EXPIRES`），
    空/空白 key 与越界 expires → 400。返回 `ok({url})`。
  - **契约补充（Task 9 决策，T25 回写 `docs/API接口清单.md`）**：`presign-upload`
    请求体在 `{size, content_type, prefix}` 之外扩展可选 `filename`（默认 `"file"`），
    `object_key = normalize_key(prefix, filename)`——调用方只给含业务标识的 prefix
    （如 `raw/REG-...`），无需自行拼文件名。
  - 存储调用统一走 `app.storage.get_storage()`（懒加载单例），测试 monkeypatch
    该引用即可（见 `tests/test_files.py`）。
- `jobs.py`：**Task 7 已实现**。`GET /jobs/{job_id}`（无前缀，完整路径 `/api/v1/jobs/{job_id}`，
  依赖 `get_current_user` 需登录）→ `ok(to_job_payload(job))`（§1.5 Job JSON）；不存在 →
  `err(40401, "任务不存在", status=404)`。业务逻辑在 `app.services.jobs`。
- `reports.py`：占位（`# filled in Task 17`）。报告导出 PDF/CSV。

## 坑/限制

- 返回统一走 `app.schemas.common` 的 `ok(data)` / `err(code, message, detail=..., status=...)` 信封；列表分页载荷用 `paginate(items, total, page, page_size)`。
- 业务错误显式 `return err(...)`，不要裸抛 `HTTPException`（全局处理器虽兜底映射，但显式错误码更可读）；错误码约定见 `docs/API接口清单.md`。
- 后续任务填充占位模块时，把 `# filled in Task N` 注释替换为真实实现即可，`router.py` 无需改动（除非新增域）。
