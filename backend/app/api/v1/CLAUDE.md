# CLAUDE.md — backend/app/api/v1/

v1 版路由。`/api/v1` 前缀由 `main.py` 挂载时统一添加，各域 router 自身不带前缀。

## 脚本

- `__init__.py`：空包。
- `router.py`：`api_router = APIRouter()`，`include_router` 聚合全部 9 个域 router。新增域时在此追加 import + include_router。
- `auth.py`：**Task 5 已实现**。router `prefix="/auth"`（完整路径 `/api/v1/auth/login`、`/api/v1/auth/me`）。`POST /login` body `{username,password}` → 查 `users` 表校验 → `ok({access_token, token_type:"bearer", user:{id,username,display_name,role,avatar}})`；用户名/密码错 → `err(40100, "用户名或密码错误", status=401)`。**防时序用户枚举（Task 5 修复）**：用户不存在时仍对模块级 `_DUMMY_HASH`（argon2，导入时算一次）跑一次 `verify_password`，使未知/已知用户名两条路径耗时相当；返回体一致。**Task 4 修复**：按用户名做失败登录限速（60s 窗口内失败 ≥5 次进入 300s cooldown，返回 `42900`），成功登录会清空失败桶/冷却状态。`GET /me`（依赖 `api.deps.get_current_user`）→ `ok(user)`。`user_payload(user)` 暴露对外字段。
- `dashboard.py`：**Task 8 已实现**。router `prefix="/dashboard"`（完整路径 `/api/v1/dashboard/*`），
  **router 级 `dependencies=[Depends(get_current_user)]` 统一要求登录**。四个端点
  `GET /stats`（统计卡）/ `GET /attributes`（属性面板）/ `GET /distributions`（分布图）/
  `GET /projects`（数据项目卡片）→ `ok(...)`。聚合逻辑在 `app.services.dashboard`。
- `welds.py`：**Task 10 已实现**。router 无前缀、`dependencies=[Depends(get_current_user)]`
  统一要求登录（完整路径 `/api/v1/*`），端点全覆盖 `docs/API接口清单.md` §3.3：
  - `GET /welds`（query `q/source/brand/status/tab/page/page_size`，服务端筛选+分页，
    按焊缝去重仅最新版本，返回 `paginate(...)` 载荷，item 含 `latest_version` 对象）；
  - `GET /welds/{weld_id}` 详情（含最新版本）;
  - `POST/GET/PATCH /registrations(/{registration_id})`（`registration_id` 兼容
    DB id / registration_no / weld_id 三种标识，`get_record_by_identifier`）。**Task 5 P2 修复**：
    `POST /registrations` 在生成编号前先抢占同 payload 的自然幂等锁（MySQL `GET_LOCK` / SQLite 进程内锁），
    正在提交中的重复请求直接 `40900`（`重复登记请求：相同表单正在提交`），避免 MySQL 顺序编号锁把双击/重放串行成两条 200；
  - `POST /registrations/{registration_id}/raw-files`（body `{object_keys[], storage_bytes?}`，
    挂 v1.0 + 累加容量 + 推导 modalities；**Task 4 修复**：只对新 key 计容量，先校验 object_key 安全性与 `stat_object()>0`，未上传/不可访问对象直接 400；重复 key 幂等不重复累计；CSV 自动导入按**本次请求中的 CSV key** 去重建 `signal_ingest`，即便该 CSV 已在版本 object_keys 中，只要尚无 ingest 记录也会补建任务。**Task 5 P2 修复**：若请求中的任一 CSV 已有 `signal_ingests` 行，则整个挂载直接 `40900`，并保持容量不重复累计）；
  - `GET/POST /welds/{weld_id}/versions(/{version_id})`（新建动作白名单
    `去噪处理|人工修正`，事务内 bump latest_version_id；**相同 action+note+object_keys
    的重复版本请求返回 40900**，并以 `data_versions.request_key` + 唯一约束兜底并发重复请求）；
  - `POST/GET /welds/{weld_id}/versions/{version_id}/validation`（同步 15 项规则核验，
    回写 `data_records.quality`，审计 validate）。
  - 业务逻辑在 `app.services.welds`；每处写操作后显式 `session.commit()`。**Task 4 修复**：除管理员外，列表/详情/登记编辑/版本/核验均按 `audit_logs(create,weld).user_id` 的稳定 owner ACL；`record.operator` 仅作展示。
    错误码：40401=焊缝/登记不存在、40402=版本不存在、40403=该版本尚未核验、40000=参数错误。
- `analysis.py`：**Task 11 ~ Task 14 已实现**。router 无前缀、`dependencies=[Depends(get_current_user)]`
  统一要求登录（完整路径 `/api/v1/*`），契约 `docs/API接口清单.md` §3.4：
  - `POST /welds/{weld_id}/versions/{version_id}/alignment-tasks`（**Task 13**）：body
    `{modalities[]}`，同事务建 pending Job（type=alignment）+ `alignment_tasks` 行 →
    **Task 4 修复：写 `create/alignment_task` 审计，且非管理员按焊缝 stable owner(user_id) 做 ownership ACL**；
    `ok({job_id})`；weld/version 缺失 → 40401/40402；**缺少所需视频/时序输入 → 40000**；
    **同 version 的 pending/running/succeeded 重复提交返回既有 `job_id`（幂等）**；failed
    旧任务会释放 `active_request_key`，下一次提交创建新的可执行 job；并发双击仍由
    `alignment_tasks.active_request_key` 唯一约束兜底。
  - `GET /alignment-tasks/{task_id}`（**Task 13**）：Job 信封（`task_id`=job_uid），成功时
    `result` 内嵌 `events/tracks/assets`（对齐产物对象键，前端经 `files.getFileUrl` 播放）；
    未执行/失败保持 result=null（契约 §1.5/§6.1）；未知 → 40401。
  - `POST /welds/{weld_id}/versions/{version_id}/split-tasks` + `GET /split-tasks/{task_id}`
    （**Task 14 切分**）：异步 Job（type=split）+ `split_tasks` 行 → `{job_id}`；body
    `{fixed_rate(>=1 帧/样本), keep_event_buffer(±s), task_format(白名单 目标检测/图像分类/
    语义分割/时序分类)}`。handler（`app.jobs.split`）按规则生成 `samples` 行并**真实写入**
    `processed/{weld_id}/split/*.jpg|*.json`；任一写失败会清理已写对象、回滚样本与任务结果；
    **缺少时序输入 → 40000**；**同 version+rules+task_format 的 pending/running/succeeded
    重复提交返回既有 `job_id`（幂等）**；failed 旧任务会释放 `active_request_key`，下一次提交
    创建新的可执行 job；并发双击仍由 `split_tasks.active_request_key` 唯一约束兜底。
    GET 返回 Job 信封（result 内嵌
    sample_count/samples（**review 修复**：`samples` 仅前 50 条预览，全量以 `samples` 表为准），
    sample_count 以 split_tasks 行为准合并）。
  - **Task 14 标注**（`app.services.annotation` 领域逻辑）：
    `GET /label-categories`（模型口径 5 类）；`POST /annotation-tasks`（body
    `{source(split_task|manual|signal), split_task_id?, version_id?, name?}`（`signal` 需 `version_id`，创建时同步生成 1 个 `meta.mode='signal'` 信号锚点样本供波形区间标注），异步 Job type=annotation +
    `annotation_tasks` 行 → `{job_id}`，成功后 handler 把来源切分样本归属到本任务）；
    `GET /annotation-tasks/{task_id}`（Job 信封）；`POST /annotation-tasks/{task_id}/import`
    （`{source(files|split_task), object_keys[]?, split_task_id?}` → `{imported}`）；
    `GET /annotation-tasks/{task_id}/samples?page=&page_size=`（分页，`page_size` 上限 100，
    每样本含 annotations[] + 样本级 confidence）；`GET …/samples/{sample_id}`（样本 + 最新
    标注 + confidence = 当前标注置信度均值）；`POST …/samples/{sample_id}/ai-pretag`（同步
    确定性 2 区域，seed=sample_id，**替换**现有标注，annotator=AI预标注）；
    `POST …/samples/{sample_id}/labels`（body `{labels[]}`，**覆盖写**，annotator=当前用户，
    confidence 缺省沿用先前同类别值，类别须在 label_categories，**按 `kind` 分支校验几何**：
    `box`→[x,y,w,h] 四元组 / `segment`→`start_time`/`end_time` 且 0<=start<end / `polygon`→
    `points` ≥3 个 [x,y] 顶点 / 未知 kind→400，**confidence 给定时须在 [0,1]**（越界如 >=10
    撞 Numeric(4,3) 列 → 400 而非 500），写审计 `update`）。
  - **坑**：标注任务相关 `{task_id}`（samples/import/labels/ai-pretag 路径）兼容 job_uid 与
    annotation_tasks 表 DB id（`annotation.resolve_annotation_task` 双解析）；`split_task_id`
    同理双解析。业务错误码 40401（焊缝/任务/样本不存在）、40402（版本不存在）、40000（参数）。
  - `GET /analysis/candidates`：quality=通过 的可分析焊缝最小载荷（`svc.list_through_welds`）；
  - `GET /welds/{weld_id}/versions/{version_id}/signals`：query `channels[]`（兼容 `channels=`
    写法，`request.query_params.getlist` 手读合并）、`filter_type/cutoff/cutoff2`（可选，真实滤波），
    **Task 4 修复：非管理员按焊缝 stable owner(user_id) 做 ownership ACL**，
    写法，`request.query_params.getlist` 手读合并）、`filter_type/cutoff/cutoff2`（可选，真实滤波），
    返回 `{duration, sample_rate, channels:[{id,name,unit,values[],lo,hi,mean}], events, anomalies}`；
  - `GET …/analysis/{mode}`：mode ∈ psd|stft|dwt|wavelet|phase|pdd，query `channel`（默认 cur）+
    滤波参数联动；phase 需 cur+vol；未知 mode/通道 → 400；
  - `GET …/analysis/result`：确定性模拟结果 `{stability, segments, anomalies}`（源自信号事件/异常，**Task 4 修复：非管理员按焊缝 stable owner(user_id) 做 ownership ACL**）。
  - `POST /features/extract`（**Task 12**）：body `{weld_id, version_id, normalization(默认无), format(默认JSON)}`
    同步真实提取三类特征（`app.services.features`：ts 8×4 + vision 8 + audio 6）→ `unify` 拼
    42 维归一化向量 → 写 `feature_extractions` 行（created_at）→ `ok(extraction)`；**返回新增 `modality_status`**（available/fallback，显式标识缺模态回退，避免把缺失模态伪装成“完整真实特征”）；**Task 4 修复：写 `extract/feature_extraction` 审计，且 POST/GET 均按焊缝 stable owner(user_id) 做 ownership ACL**；normalization/
    format 白名单校验，非法 → 40000；weld/version 缺失 → 40401/40402。
  - `GET /features/{extraction_id}`（**Task 12**）：特征提取结果（导出用）；不存在 → 40401。
    载荷 `_extraction_payload`（created_at 复用 `jobs._iso_utc`）。
  - 信号由 `app.services.signals` 确定性生成（seed = crc32(weld_id)）、DSP 由 `app.services.dsp`
    真实计算（scipy/pywt，非罐头数字）。
  - 坑：`/analysis/result` 是具体路径，必须在 `/analysis/{mode}` 之前注册（FastAPI 按顺序匹配）；
    `cutoff/cutoff2` 为 0~1 归一化频率（相对奈奎斯特）；错误码 40401/40402/40000。
- `datasets.py`：**Task 15 已实现**。router 无前缀、`dependencies=[Depends(get_current_user)]`
  统一要求登录（完整路径 `/api/v1/*`），契约 `docs/API接口清单.md` §3.5，业务逻辑在
  `app.services.datasets`：
  - `GET /datasets`（列表，含当前版本号/划分/质量）、`POST /datasets`（body `{name, task,
    source?}`，同名 → 40900，空名/空任务 → 40000）、`GET /datasets/{dataset_id}`（详情；
    `dataset_id` 兼容 DB id / dataset_no，不存在 → 40401；**详情新增 `label_distribution`**，返回当前版本标注类别计数）。
  - `GET /datasets/{dataset_id}/dimensions`（7 项 `{name, status, required}`）、
    `GET /datasets/{dataset_id}/readiness`（`{readiness, checks[]}`）。
  - `GET/POST /datasets/{dataset_id}/versions`（新建固定快照占位，下一版本号）、
    `GET /datasets/{dataset_id}/versions/{version_id}`（数据集不存在 → 40401；版本不存在或不属于该数据集 → 40402）、
    `GET /datasets/{dataset_id}/versions/{version_id}/items`（按样本粒度分页；`q` 过滤
    weld_id/weld_name/registration_no，`quality` 精确，`split` 仅 train/val/test；
    服务端按 `sample_id` 稳定排序，SQL 侧过滤/计数/offset/limit，40401/40402/40000 对齐）；**Task 2–4 前端**以 `listDatasetVersionItems(datasetId, versionId, {q,quality,split,page,page_size})` 消费该端点，数据中心成员列表不得改走全局 `/welds`。
  - `POST /datasets/{dataset_id}/versions/{version_id}/build-tasks`（**异步**，body `{source}` =
    DatasetSource 字典或类型字符串；类型白名单校验 → 40000；同事务建 pending Job +
    `dataset_build_tasks` 行 → `{job_id}`；完整来源经 `create_job(result={"source":...})` 携带；
    状态经通用 `GET /jobs/{job_id}` 轮询）。
  - `GET /datasets/{dataset_id}/lineage`（4 层节点）。
  - 错误码：40401=数据集不存在、40402=数据集版本不存在（含版本不属于该数据集）、40900=同名冲突、40000=参数。
- `models.py`：**Task 16 已实现**。router 无前缀、`dependencies=[Depends(get_current_user)]`
  统一要求登录（完整路径 `/api/v1/*`），契约 `docs/API接口清单.md` §3.6，业务逻辑在
  `app.services.models`：
  - `GET /models`（列表 + 汇总 `{summary:{total, prod_candidates, recent_training, gpu_usage=42},
    models[]}`，models 含最新版本号/指标/状态/权重键）、`GET /models/{model_id}`（详情 +
    版本列表）、`POST /models`（body `{name, type, description?}`，同名 → 40900，空名/空类型 →
    40000）、`PATCH /models/{model_id}/versions/{vid}`（body `{status?, note?}`，status 白名单
    生产候选/训练中/实验版本 → 40000；**note 无对应列仅接受不落库**；模型不存在 40401、版本
    不属于该模型 40402）。
  - `POST /training-tasks`（**异步**：body `{dataset_version_id, base_model_id?, epochs,
    batch_size, learning_rate, val_ratio, ...高级参数}`，`extra=allow` 收集高级参数进
    hyperparams；数据集版本/基础模型版本不存在 → 40401；**指定版本 readiness=暂不可训练 → 40000 拒绝**；**同 dataset_version 的 pending/running 训练任务返回既有 `job_id`（防重复活动 job）**；同事务建 pending Job(type=training) +
    `training_tasks` 行 → `{job_id}`）、`GET /training-tasks/{task_id}`（Job 信封，result 内嵌
    metrics/loss_curve/model_version）、`GET /training-tasks/{task_id}/logs`（确定性日志文本）。
  - `POST /test-tasks`（body `{model_version_id, dataset_version_id, tasks[]}` → `{job_id}`；**模型/数据集版本不匹配**或**无 test split** → 40000）、
    `GET /test-tasks/{task_id}`（Job 信封，result 内嵌 metrics + confusion_matrix 2×2）。
  - `POST /inference-tasks`（body `{model_version_id, input, input_type}` → `{job_id}`，
    空 input/input_type → 40000；**真实文件校验**：拒绝损坏/伪装图片、gif 等不支持格式、>100MB 输入；**同 model_version+input_key+input_type 对 pending/running/succeeded 幂等返回既有 `job_id`**）、`GET /inference-tasks/{task_id}`（Job 信封，result 内嵌
    boxes/categories/confidence/latency_ms）。
  - 坑：各域 `{task_id}` 均为 job_uid（`get_job_by_uid`）；GET 在任务未执行/失败时保持
    result=null，域字段（metrics/loss_curve/confusion_matrix/result）仅在 succeeded 后从
    任务表合并进 result（对齐 alignment-tasks 模式）。错误码：40401=模型/任务/数据集版本/
    模型版本不存在、40402=版本不属于该模型、40900=同名冲突、40000=参数。
- `files.py`：**Task 9 已实现**。router `prefix="/files"`（完整路径 `/api/v1/files/*`），
  **router 级 `dependencies=[Depends(get_current_user)]` 统一要求登录**。三个端点：
  - `POST /upload`（multipart `file`，小文件 <100MB 后端代理）：object_key 前缀
    固定 `uploads/{uuid}`，流式读取 + 字节计数封顶（`MAX_PROXY_UPLOAD_SIZE`，
    Content-Length 有则先快速拒绝），`upload_stream` 后 `presign_get` 返回
    `ok({object_key, url, lifecycle})`。`lifecycle={policy:temporary,retention_days:30,prefix:'uploads/'}` 对齐 OSS `uploads/` 30 天清理策略（**不承诺立即删除**）；超限 → `err(40000, ..., status=400)`。**Task 5 P2 修复**：CSV 代理上传新增 5MB 默认门槛（`MAX_PROXY_CSV_UPLOAD_SIZE`），超限直接 `40000` 提示改走 `presign-upload` + 挂载异步导入，避免 60s+ 静默超时；长文件名/长 object key 的审计写入不再 500。
  - `POST /presign-upload`（body `{size, content_type, prefix, filename?}`）：
    校验 `0 < size ≤ 2GB`（`MAX_PRESIGN_UPLOAD_SIZE`），调 `presign_put` 返回
    `ok({object_key, upload_url, lifecycle?})`；当对象键落在 `uploads/` 前缀时附带同样的 30 天临时保留策略元数据；**Task 4 修复**：拒绝绝对路径/反斜杠/`..` 路径穿越 prefix，并写 `presign_upload/file` 审计；空 prefix（normalize_key 抛 ValueError）→ 400。
  - `GET /{object_key:path}/url?expires=`：object_key 含 `/`（如 `uploads/<uuid>/x.mp4`），
    用 `:path` 捕获；`expires` 默认 3600、上限 86400（`MAX_PRESIGN_GET_EXPIRES`），
    **Task 4 修复**：同时校验原始请求路径与归一化后的 `object_key` 一致，拒绝绝对路径/反斜杠/`..` 穿越；空/空白 key 与越界 expires → 400。返回 `ok({url})`。
  - **契约补充（Task 9 决策，T25 回写 `docs/API接口清单.md`）**：`presign-upload`
    请求体在 `{size, content_type, prefix}` 之外扩展可选 `filename`（默认 `"file"`），
    `object_key = normalize_key(prefix, filename)`——调用方只给含业务标识的 prefix
    （如 `raw/REG-...`），无需自行拼文件名。
  - 存储调用统一走 `app.storage.get_storage()`（懒加载单例），测试 monkeypatch
    该引用即可（见 `tests/test_files.py`）。
- `jobs.py`：**Task 7 已实现**。`GET /jobs/{job_id}`（无前缀，完整路径 `/api/v1/jobs/{job_id}`，
  依赖 `get_current_user` 需登录）→ `ok(to_job_payload(job))`（§1.5 Job JSON）；不存在 →
  `err(40401, "任务不存在", status=404)`。业务逻辑在 `app.services.jobs`。
- `reports.py`：**Task 17 已实现**。router 无前缀、`dependencies=[Depends(get_current_user)]`
  统一要求登录（完整路径 `/api/v1/reports/export`），契约 `docs/API接口清单.md` §3.7，业务逻辑在
  `app.services.reports`：
  - `POST /reports/export` body `{type(validation|analysis|annotation|features|test|data-list),
    ref_ids[], format(pdf|json)}` → 每 ref_id 生成报告写 MinIO
    `reports/{type}/{ref_id}.pdf|.json` → `ok({urls:[{ref_id, url}]})`（url 预签名下载）。**Task 4 修复**：导出成功后写 `export/report` 审计；非管理员对可归属焊缝的报告类型按 stable owner(user_id) 做 ownership ACL；`data-list` 空 `ref_ids` 仅导出本人可见记录，指定 weld/registration 需逐条过权。
  - 未知 type / format → 400（40000）；引用实体不存在 → 404（40401）；未登录 401（40100）。
  - `data-list`：`ref_ids=[]` → 全量单份（ref_id=`all`）；非空 → 逐标识（DB id/weld_id/
    registration_no）解析过滤，缺失 404。

## 坑/限制

- 返回统一走 `app.schemas.common` 的 `ok(data)` / `err(code, message, detail=..., status=...)` 信封；列表分页载荷用 `paginate(items, total, page, page_size)`。
- 业务错误显式 `return err(...)`，不要裸抛 `HTTPException`（全局处理器虽兜底映射，但显式错误码更可读）；错误码约定见 `docs/API接口清单.md`。
- 后续任务填充占位模块时，把 `# filled in Task N` 注释替换为真实实现即可，`router.py` 无需改动（除非新增域）。
