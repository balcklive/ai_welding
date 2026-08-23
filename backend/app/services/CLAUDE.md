# CLAUDE.md — backend/app/services/

业务服务层：跨域复用的领域逻辑（Job 通用服务）。当前进度：Task 7（通用 Job 服务）。

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

## 坑/限制

- **commit 归属**：本服务所有写操作**不 commit**，只 flush/改内存属性。调用方必须自行 commit
  （如路由 `Depends(get_session)` 的 session 由请求上下文 commit/close），否则数据不落库。
  测试 `tests/test_jobs.py::test_create_job_does_not_commit` 用 rollback 验证该约定。
- 状态机仅 `pending → running → succeeded | failed`（§6.1），服务层不做状态校验（幂等粗粒度），
  跨状态调用（如未 running 直接 succeeded）由调用方约定。
- 新增跨域服务（如任务执行器、特征提取）放本目录，避免各域路由重复造轮子。
