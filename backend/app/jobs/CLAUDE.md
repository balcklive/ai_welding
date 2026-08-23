# CLAUDE.md — backend/app/jobs/

Job 执行器与各域 handler（Task 13 ~ Task 16）。导入本包即完成 handler 注册
（`__init__.py` 拉入 `app/jobs/alignment.py` / `app/jobs/split.py` / `app/jobs/annotation.py` /
`app/jobs/dataset_build.py` / `app/jobs/training.py` / `app/jobs/testing.py` /
`app/jobs/inference.py`，各模块级 `@register_handler(...)` 填充 `executor.HANDLERS`）。
新增域任务（split/annotation/dataset_build/training...）在本包加一个 `xxx.py` 注册即可，
executor 无需改动。

## 脚本

- `__init__.py`：**导入即注册**——`from app.jobs import executor`（lifespan 用）会顺带执行
  `app/jobs/alignment.py` 的注册。re-export `HANDLERS/register_handler/run_job/start/stop`。
- `executor.py`：**Task 13**。DB 轮询执行器：
  - `HANDLERS: dict[job type → (job_id:int, session:Session) -> None]`，用
    `@register_handler("type")` 装饰器注册。
  - `start()` / `stop()`：daemon 线程，每 ~1s 轮询 `pending` job（批 5）。**原子领单**：
    对每个候选发条件 UPDATE `WHERE id AND status='pending'`（`rowcount==1` 才算领到），
    并发/多执行者不会重复领同一 job（review 修复；原 SELECT→mark_running→commit 非原子）。
  - 线程生命周期（review 修复，防双轮询）：`stop()` 只在确认线程真正退出（join 返回且
    `is_alive()` False）后丢弃引用，超时仍存活则保留；`start()` 若上一线程仍存活则拒绝
    重复启动（no-op + 告警），且只在确认旧线程已死后才清 `_stop`。
  - `run_job(job_uid)`：**同步**入口（测试/手动），不启动线程；全程用**一个**独立
    `Session`（`SessionLocal`）；同样原子领单（非 pending 跳过），失败 → `mark_failed`
    + commit。
  - 失败兜底：任意 `Exception` → loguru traceback → failed，**绝不滞留 running**；
    未注册 type → `ValueError` 同样走 failed。
  - `_dispatch` / `_mark_failed_in`：handler 执行 + 失败回写（事务脏先 `rollback` 再写）。
- `alignment.py`：**Task 13**。`handle(job_id, session)`（`@register_handler("alignment")`）——
  按 `alignment_tasks.job_id` 取任务 → 调 `app.services.alignment.simulate_alignment`
  （模拟进度 + 自动生成「时间对齐」版本 + 回填 task 域字段与 job.result）。
- `split.py`：**Task 14**。`handle(job_id, session)`（`@register_handler("split")`）→
  `simulate_split(session, task, job)`（**领域逻辑直接在本模块**，任务清单未规划 split service）：
  解析规则 `fixed_rate`（帧/样本，>=1）→ `sample_count = max(1, int(DURATION*1000)//fixed_rate)`
  （DURATION=signals 5.42s → 5420 帧，确定性）→ 进度逐步 → 逐样本建 `Sample` 行
  （frame_no 0..n，`object_keys=processed/{weld_id}/split/{sample.id}.jpg|.json`，
  **先 flush 拿 id 再回填 object_keys**）→ 回填 `task.sample_count` + `job.result`
  `{sample_count, rules, task_format, samples[]}`（**review 修复**：`samples` 只内嵌前 50 条
  预览，防 fixed_rate=1 → 5420 条 ~500KB 塞进 result 每轮询回传；全量样本以 `samples` 表为准）。
- `annotation.py`：**Task 14**。`handle(job_id, session)`（`@register_handler("annotation")`）→
  `app.services.annotation.simulate_annotation`（进度逐步 → 若 source=split_task 把该切分任务
  样本 `annotation_task_id` 指向本任务 → 回填 job.result `{source, name, samples_count}`）。
  AI 预标注/标注保存是**同步端点**，不经 handler。
- `dataset_build.py`：**Task 15**。`handle(job_id, session)`（`@register_handler("dataset_build")`）→
  `app.services.datasets.run_build`（进度逐步 → 按来源 gather 候选样本 → 空则兜底合成 →
  按 record_id 分组 8:1:1 划分防泄漏 → 落 `dataset_items` → 计算 quality → 快照写 MinIO →
  回填 dataset_versions + datasets → job.result `{item_count, split, quality, snapshot_id}`）。
  **完整来源（type + 各 id）随创建时 `Job.result={"source":...}` 携带**——`dataset_build_tasks.source`
  仅 VARCHAR(32) 存类型字符串（契约 §3.22），handler 从 `job.result` 读全量来源。
- `training.py`：**Task 16**。`handle(job_id, session)`（`@register_handler("training")`）→
  `app.services.models.run_training`（进度逐步 → 确定性指标/损失曲线 → **同事务生成
  `model_versions`（status=实验版本，挂 base 模型或自动新建 Model）+ 权重占位写 MinIO
  `models/{id}/weights.pt` 尽力而为** → 回填 training_tasks.metrics/loss_curve →
  job.result `{metrics, loss_curve, model_version}`）。
- `testing.py`：**Task 16**。`handle(job_id, session)`（`@register_handler("test")`）→
  `app.services.models.run_test`（进度逐步 → metrics `{accuracy 0.968, recall 0.942, f1 0.955,
  latency_ms 18}` + confusion_matrix `[[612,18],[22,596]]` → 回填 test_tasks →
  job.result `{metrics, confusion_matrix}`）。
- `inference.py`：**Task 16**。`handle(job_id, session)`（`@register_handler("inference")`）→
  `app.services.models.run_inference`（进度逐步 → 确定性 boxes/categories/confidence/latency_ms
  （seed=task.id）→ 回填 inference_tasks.result → job.result 同款）。

## 坑/限制

- **Session 归属**：每个 handler 拿到的是执行器专用的独立 `Session`（`SessionLocal`，
  `expire_on_commit=False`），**不是**请求 session；handler 自行 commit（进度逐步 commit 让
  轮询可见），失败由 executor 兜底。不要在里面用请求 session 的约定（不 commit）推理。
- **`run_job` 别开两个 session 同时用**：`SessionLocal` 在测试里可能绑同一引擎
  （StaticPool 单连接），两个活跃 Session 抢同一连接会冲突；`run_job` 已改为一个 session
  全程，轮询线程对每个已领 job 各自开一个 session（前一个已 close）。
- **别在 `HANDLERS` 里硬编码调度逻辑**：新增域任务（split/annotation/training...）在本包加
  一个 `xxx.py`，`@register_handler("type")` 注册即可，executor 无需改动。
