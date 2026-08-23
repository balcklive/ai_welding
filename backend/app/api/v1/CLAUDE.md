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
- `welds.py`：**Task 10 已实现**。router 无前缀、`dependencies=[Depends(get_current_user)]`
  统一要求登录（完整路径 `/api/v1/*`），端点全覆盖 `docs/API接口清单.md` §3.3：
  - `GET /welds`（query `q/source/brand/status/tab/page/page_size`，服务端筛选+分页，
    按焊缝去重仅最新版本，返回 `paginate(...)` 载荷，item 含 `latest_version` 对象）；
  - `GET /welds/{weld_id}` 详情（含最新版本）；
  - `POST/GET/PATCH /registrations(/{registration_id})`（`registration_id` 兼容
    DB id / registration_no / weld_id 三种标识，`get_record_by_identifier`）；
  - `POST /registrations/{registration_id}/raw-files`（body `{object_keys[], storage_bytes?}`，
    挂 v1.0 + 累加容量 + 推导 modalities）；
  - `GET/POST /welds/{weld_id}/versions(/{version_id})`（新建动作白名单
    `去噪处理|人工修正`，事务内 bump latest_version_id）；
  - `POST/GET /welds/{weld_id}/versions/{version_id}/validation`（同步 15 项规则核验，
    回写 `data_records.quality`，审计 validate）。
  - 业务逻辑在 `app.services.welds`；每处写操作后显式 `session.commit()`。
    错误码：40401=焊缝/登记不存在、40402=版本不存在、40403=该版本尚未核验、40000=参数错误。
- `analysis.py`：**Task 11 + Task 12 + Task 13 已实现**。router 无前缀、`dependencies=[Depends(get_current_user)]`
  统一要求登录（完整路径 `/api/v1/*`），契约 `docs/API接口清单.md` §3.4：
  - `POST /welds/{weld_id}/versions/{version_id}/alignment-tasks`（**Task 13**）：body
    `{modalities[]}`，同事务建 pending Job（type=alignment）+ `alignment_tasks` 行 →
    `ok({job_id})`；weld/version 缺失 → 40401/40402。
  - `GET /alignment-tasks/{task_id}`（**Task 13**）：Job 信封（`task_id`=job_uid），成功时
    `result` 内嵌 `events/tracks/assets`（对齐产物对象键，前端经 `files.getFileUrl` 播放）；
    未执行/失败保持 result=null（契约 §1.5/§6.1）；未知 → 40401。
  - `GET /analysis/candidates`：quality=通过 的可分析焊缝最小载荷（`svc.list_through_welds`）；
  - `GET /welds/{weld_id}/versions/{version_id}/signals`：query `channels[]`（兼容 `channels=`
    写法，`request.query_params.getlist` 手读合并）、`filter_type/cutoff/cutoff2`（可选，真实滤波），
    返回 `{duration, sample_rate, channels:[{id,name,unit,values[],lo,hi,mean}], events, anomalies}`；
  - `GET …/analysis/{mode}`：mode ∈ psd|stft|dwt|wavelet|phase|pdd，query `channel`（默认 cur）+
    滤波参数联动；phase 需 cur+vol；未知 mode/通道 → 400；
  - `GET …/analysis/result`：确定性模拟结果 `{stability, segments, anomalies}`（源自信号事件/异常）。
  - `POST /features/extract`（**Task 12**）：body `{weld_id, version_id, normalization(默认无), format(默认JSON)}`
    同步真实提取三类特征（`app.services.features`：ts 8×4 + vision 8 + audio 6）→ `unify` 拼
    42 维归一化向量 → 写 `feature_extractions` 行（created_at）→ `ok(extraction)`；normalization/
    format 白名单校验，非法 → 40000；weld/version 缺失 → 40401/40402。
  - `GET /features/{extraction_id}`（**Task 12**）：特征提取结果（导出用）；不存在 → 40401。
    载荷 `_extraction_payload`（created_at 复用 `jobs._iso_utc`）。
  - 信号由 `app.services.signals` 确定性生成（seed = crc32(weld_id)）、DSP 由 `app.services.dsp`
    真实计算（scipy/pywt，非罐头数字）。
  - 坑：`/analysis/result` 是具体路径，必须在 `/analysis/{mode}` 之前注册（FastAPI 按顺序匹配）；
    `cutoff/cutoff2` 为 0~1 归一化频率（相对奈奎斯特）；错误码 40401/40402/40000。
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
