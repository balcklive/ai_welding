# CLAUDE.md — backend/app/services/

业务服务层：跨域复用的领域逻辑。当前进度：Task 7（通用 Job 服务）+ Task 8（Dashboard 总览聚合查询）。

## 脚本

- `__init__.py`：空包。
- `jobs.py`：**Task 7**。通用异步任务生命周期（§1.5 / §3.6）：
  - `create_job(session, type, result=None) -> Job`：`job_uid=f"job_{uuid4().hex[:8]}"`，
    status=`pending`、progress=0、`created_at=datetime.now(timezone.utc)`（UTC aware）。
    **只 `add` + `flush`，不 commit**——由调用方（路由/执行器）统一 commit，保证与业务变更同事务。
  - `get_job_by_uid(session, uid) -> Job | None`：按 job_uid 查，不存在返回 None。
  - `mark_running(session, job)`：status=`running`，清空 finished_at（兼容重跑）。
  - `mark_succeeded(session, job, result)`：status=`succeeded`、progress=100、写 result + finished_at。
  - `mark_failed(session, job, error)`：status=`failed`、写 error + finished_at（progress 保留失败时值）。
  - 四个 mark_* 均只改内存属性，**不 commit**，调用方 commit。
  - `to_job_payload(job) -> dict`：输出 §1.5 的 Job JSON
    `{id, type, status, progress, result, error, created_at, finished_at}`；`id` = `job_uid`；
    时间为 ISO-8601 UTC 字符串（`...Z`，内部 `_iso_utc`）；result/error 原样透传（None/dict，JSON 安全）。
  - `_iso_utc(dt) -> str | None`：时间序列化。**naive datetime 一律按 UTC 补 tzinfo 再转换**
    （SQLite/MySQL 读回时 tzinfo 被剥离，naive 即 UTC），避免 `astimezone` 按系统本地时区偏移。
- `dashboard.py`：**Task 8**。总览四端点聚合查询（`get_stats` / `get_attributes` /
  `get_distributions` / `get_projects`），供 `app/api/v1/dashboard.py` 路由调用。
  形状对齐 `src/App.tsx` Overview 消费常量（manufacturers/transitionTypes/weldingTypes/
  defectTypes/wordCloud/projects），**tone/颜色由前端映射，后端不输出**。模块级常量
  `DEFECT_VOCAB`（统计口径缺陷词表：气孔/焊瘤/未焊透/焊穿/咬边/夹渣，§3.2 与标注
  "标签类别"是两套词表勿混用）、`TRANSITION_BY_WELD_METHOD`（weld_method→过渡类型映射）。
  时间序列化复用 `jobs._iso_utc`（不重复造轮子）。**计数一律用单条 group_by 查询**
  （`_defect_counts` 按 category、`_weld_method_counts` 按 weld_method）汇总后查 dict，
  词表缺失默认 0，**避免 per-词条 N+1 查询**（评审发现并已修复）。

## 坑/限制

- **commit 归属**：本服务所有写操作**不 commit**，只 flush/改内存属性。**commit 永远是调用方的职责**，
  不显式 commit 则数据不落库。特别注意：路由 `Depends(get_session)` 的请求 session
  （`core/db.py` 的 `get_session`）退出时**只 `close()`，不 commit**——`Session.close()` 会回滚
  未提交事务；因此路由若在响应前改了 job 状态（如异步执行器回调建/转 job），必须显式 `session.commit()`。
  测试 `tests/test_jobs.py::test_create_job_does_not_commit` 用 rollback 验证该约定。
- **`session.exec(select(单列/聚合函数))` 是 `SelectOfScalar`，返回标量结果**（`.one()`/`.all()`
  直接给值，不是 Row）；只有 `select(多列)` / `select(模型)` 才返回 Row。dashboard.py 的聚合助手
  （`_count`/`_first_scalar`/`_distinct_scalars`）已按此约定取值，勿再套 `[0]`——对 int 下标会炸
  （`'int' object is not subscriptable`）。多列 `select(Annotation.category, func.count(...))`
  是 Row，可 `for cat, cnt in rows` 解包。
- 状态机仅 `pending → running → succeeded | failed`（§6.1），服务层不做状态校验（幂等粗粒度），
  跨状态调用（如未 running 直接 succeeded）由调用方约定。
- 新增跨域服务（如任务执行器、特征提取）放本目录，避免各域路由重复造轮子。
