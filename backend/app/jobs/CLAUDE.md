# CLAUDE.md — backend/app/jobs/

Job 执行器与各域 handler（Task 13）。导入本包即完成 handler 注册（`__init__.py` 拉入
`app/jobs/alignment.py`，其模块级 `@register_handler("alignment")` 填充 `executor.HANDLERS`）。

## 脚本

- `__init__.py`：**导入即注册**——`from app.jobs import executor`（lifespan 用）会顺带执行
  `app/jobs/alignment.py` 的注册。re-export `HANDLERS/register_handler/run_job/start/stop`。
- `executor.py`：**Task 13**。DB 轮询执行器：
  - `HANDLERS: dict[job type → (job_id:int, session:Session) -> None]`，用
    `@register_handler("type")` 装饰器注册。
  - `start()` / `stop()`：daemon 线程，每 ~1s 轮询 `pending` job（批 5）。**领单语义**：
    先 `mark_running` + `commit`（轮询/并发不重复领）再跑 handler。
  - `run_job(job_uid)`：**同步**入口（测试/手动），不启动线程；全程用**一个**独立
    `Session`（`SessionLocal`），失败 → `mark_failed(job, {"message": str(e)})` + commit。
  - 失败兜底：任意 `Exception` → loguru traceback → failed，**绝不滞留 running**；
    未注册 type → `ValueError` 同样走 failed。
  - `_dispatch` / `_mark_failed_in`：handler 执行 + 失败回写（事务脏先 `rollback` 再写）。
- `alignment.py`：**Task 13**。`handle(job_id, session)`（`@register_handler("alignment")`）——
  按 `alignment_tasks.job_id` 取任务 → 调 `app.services.alignment.simulate_alignment`
  （模拟进度 + 自动生成「时间对齐」版本 + 回填 task 域字段与 job.result）。

## 坑/限制

- **Session 归属**：每个 handler 拿到的是执行器专用的独立 `Session`（`SessionLocal`，
  `expire_on_commit=False`），**不是**请求 session；handler 自行 commit（进度逐步 commit 让
  轮询可见），失败由 executor 兜底。不要在里面用请求 session 的约定（不 commit）推理。
- **`run_job` 别开两个 session 同时用**：`SessionLocal` 在测试里可能绑同一引擎
  （StaticPool 单连接），两个活跃 Session 抢同一连接会冲突；`run_job` 已改为一个 session
  全程，轮询线程对每个已领 job 各自开一个 session（前一个已 close）。
- **别在 `HANDLERS` 里硬编码调度逻辑**：新增域任务（split/annotation/training...）在本包加
  一个 `xxx.py`，`@register_handler("type")` 注册即可，executor 无需改动。
