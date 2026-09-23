# CLAUDE.md — backend/app/jobs/

Job 执行器与各域 handler（Task 13 ~ Task 16 + **Task 18** + **media_prep**）。导入本包即完成 handler 注册
（`__init__.py` 拉入 `app/jobs/alignment.py` / `app/jobs/split.py` / `app/jobs/annotation.py` /
`app/jobs/dataset_build.py` / `app/jobs/training.py` / `app/jobs/testing.py` /
`app/jobs/inference.py` / `app/jobs/signal_ingest.py` / `app/jobs/media_prep.py`，各模块级 `@register_handler(...)`
填充 `executor.HANDLERS`）。
新增域任务（split/annotation/dataset_build/training/signal_ingest/media_prep...）在本包加一个 `xxx.py`
注册即可，executor 无需改动。

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
    对 `alignment`/`split` 还会同步清空任务行的 `active_request_key`，让 failed 请求可直接重试；
    未注册 type → `ValueError` 同样走 failed。
  - `_dispatch` / `_mark_failed_in`：handler 执行 + 失败回写（事务脏先 `rollback` 再写）。
  - **MLflow（2026-08-29）**：`training/test/inference` Job 首次运行时若 `mlflow_run_id` 为空，
    调 `mlflow_integration.start_run(job_uid, type)` 建 RUNNING Run 并回写；失败兜底时对已有
    run_id 调 `finish_run(run_id, "FAILED")` 保留失败历史（best-effort，MLflow 不可用不阻塞 Job）。
- `alignment.py`：**Task 13（对齐真实化后为真实内核）**。`handle(job_id, session)`（`@register_handler("alignment")`）——
  按 `alignment_tasks.job_id` 取任务 → 调 `app.services.alignment.run_alignment`
  （真实信号事件 + ffmpeg 视频探测/关键帧 + 真实产物 CSV/JPG/tracks.json，部分成功语义；
  自动生成「时间对齐」版本 + 回填 task 域字段与 job.result；MinIO 任一写失败会清理已写对象）。
- **分析产物版本幂等（T16.3/R7，2026-09-14）**：`split.py` 与 `features.py` 生成「样本分段」/「特征提取」版本时统一走 `services.welds.reuse_or_create_version`——**同一个产物只产生一个版本**（幂等身份 = action + note + object_keys：note 里带任务 id/维度、object_keys 里带产物键，所以"同任务重入复用、换参数重跑新建"）。`features.py` 的产物键另带**提取参数的短哈希**（`features/{version_id}-{params_tag}.json`），否则"同源版本换归一化/输出格式重跑"会互相覆盖同一个文件。**对齐不接入**（产物键与 note 都不带任务身份）。
- `split.py`：**Task 14 + T10 + v3 分流（2026-09-22）**。`handle(job_id, session)` 按 `rules`
  的 `rules_version` 分流：**`>= 3` 走 `_run_v3`**（秒级窗口 + `splitting.map_window_to_modalities`
  产出多模态样本包 + `samples.start_time/end_time` 真列 + `samples/{index:06d}.json` +
  任务级 `manifest.json` + **焊缝图片按 ROI 投影裁切**——`_crop_seam_image` 任何失败只告警、
  样本照常成立，图片是增强模态）+ **逐段视频代表帧**（2026-09-23）——`_extract_video_frames`
  对每个窗口抽**本段自己的**帧（时刻取自 `splitting.representative_frame_time`，与预览**同一个
  函数**，故"预览看到的那一帧"就是"样本里存的那一帧"），落
  `processed/{weld}/split/{task}/samples/{段号:06d}.frame.jpg` 并进样本 `object_keys` 与
  `meta.video.frame.object_key`；键名带 `.frame.jpg` 后缀是为了**不与同目录的焊缝图片切片
  `{段号:06d}.jpg` 互相覆盖**（`test_split_v3_api.py` 有断言钉这一点）。整批抽帧失败（视频不可读/
  超 `media_probe.MAX_VIDEO_PROBE_BYTES`/ffmpeg 不可用）只告警返回空、样本照常——视频同样是
  增强模态，与 `_crop_seam_image` 同一取舍）；**`<= 2` 走 `_run_legacy`**，行为逐字保留，好让历史
  `failed` 任务仍能重试（不能拿 v3 去重切历史口径）。Job **不做任何时间换算**——换算全在
  `splitting.map_window_to_modalities`，且预览走同一个函数。历史 `_run_legacy` 口径：
  `handle(job_id, session)`（`@register_handler("split")`）→
  `simulate_split(session, task, job)`（**领域逻辑直接在本模块**，任务清单未规划 split service）：
  读 `window_seconds`/`stride_seconds`（**秒**，T10 起）；历史任务没有这两个键时用 `_rule_seconds`
  按旧口径换算（`fixed_rate`/`stride` 是采样点数 → `点数 ÷ 采样率`，结果与旧实现一致，不重跑）
  （DURATION=signals 5.42s → 5420 帧，确定性）→ 进度逐步 → 逐样本建 `Sample` 行
  （frame_no = **任务内序号** 1..n（不是真实视频帧号，勿用于跨任务判重，见 services/CLAUDE.md 的 T11 段），
  `meta` 含 `sample_index/window_start/window_end/frame_start/frame_end（采样点下标）/window_seconds/video_frame_no/video_frame_start/video_frame_end/source_version_id/task_format`
  （**2026-09-22 统一坐标**：窗口的秒是**信号时间**，视频帧号须按 `t_video = t_signal - offset` 换算，
  offset 经 `alignment.resolve_calibration` + `calibration_offset_seconds` 从**该焊缝 v1.0 标定**取——
  与对齐服务同一个 resolver，两处各读一次就会漂移；换算后整段仍为负 → 本窗没有视频内容、不记这三个键）
  与 **`rules_version`**（默认 1 = 旧口径"帧=采样点"；T10 的新任务由 rules 携带 2，供 D16-A 区分新旧切片），
  `object_keys=processed/{weld_id}/split/{sample.id}.jpg|.json`，
  **先 flush 拿 id 再回填 object_keys**）并**真实写入 JPG/JSON 到 MinIO**；任一写失败会清理已写对象并回滚样本/
  `task.sample_count`/`job.result` → 回填 `task.sample_count` + `job.result`
  `{sample_count, rules, task_format, samples[]}`（**review 修复**：`samples` 只内嵌前 50 条
  预览，防 fixed_rate=1 → 5420 条 ~500KB 塞进 result 每轮询回传；全量样本以 `samples` 表为准）。
- `annotation.py`：**Task 14**。`handle(job_id, session)`（`@register_handler("annotation")`）。
  **2026-09-06 LS 接线（决策 2）**：`label_studio_mode=on` 时改走
  `app.services.annotation_ls.prepare_ls_task`（归位样本 → 推 LS → 置 `ls_status=pending_ls`
  等待态）并 commit 后返回——**job 保持 running，不立即 succeeded**，完成由全部样本回写
  驱动（`handle_annotation_event` → `_maybe_complete_task`）；`off`/LS client 不可达则回退
  `app.services.annotation.simulate_annotation`（进度逐步 → 若 source=split_task 把该切分任务
  样本 `annotation_task_id` 指向本任务 → 回填 job.result `{source, name, samples_count}`）。
  **2026-09-07**：`source=signal/video`（媒体导出桥未落地）同样回退 simulate——其锚点样本
  `object_keys=[]` 推流必为 0，进 LS 等待态会 0 条 task + 永无回写 → job 永久 running。
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
- `features.py`：**Task 12 + T16.3**。`handle(job_id, session)`（`@register_handler("feature_extraction")`）——
  读 `job.result.request`（weld_id/version_id/normalization/format）→ 真实信号/视觉/音频特征 → `unify`
  拼 42 维向量 → 落 `feature_extractions` 行 → **T16.3：产物写 MinIO**
  `processed/{weld_id}/features/{version_id}.json`（写失败仅告警，不让成功的提取变失败）+ **仅当
  `status == "succeeded"` 才 `create_version(action="特征提取")`**，`object_keys` = 源版本文件 ∪ 产物
  （合并源版本是必须的：只挂产物会让"读原始信号"断链，T16.2/D18）。partial（缺模态/启发式模态）只落库
  不产版本。
- `signal_ingest.py`：**Task 18**。`handle(job_id, session)`（`@register_handler("signal_ingest")`）
  → 按 `signal_ingests.job_id` 取任务 → `app.services.signal_ingest.run_ingest`（下载 CSV → 10 条
  校验 → 启发式 events/anomalies → 写 MinIO Parquet → 回填行 + job.result）。**关键差异**：
  `run_ingest` 内部自捕获异常并写 failed 行状态后正常返回——executor 的 failed 兜底会先
  `rollback` 丢弃 handler 写过的行状态，故不能像 alignment/split 把业务异常重抛给执行器。
- `media_prep.py`：**视频可播性预处理**。`handle`（`@register_handler("media_prep")`）→
  `run_media_prep(session, job)`——登记挂载视频 key 时由 welds 路由同事务建 job
  （`result={weld_id, version_id, object_key}`）；handler 下载源视频（≤`MAX_VIDEO_PROBE_BYTES`
  否则 ValueError failed）→ `_probe_codec`（ffmpeg stderr 解析编码）→ 已是
  `BROWSER_FRIENDLY_CODECS`+faststart 则 `preview_key=object_key` 免转；否则
  `media_probe.transcode_preview` 转 H.264+faststart 上传
  `processed/{weld_id}/video/{stem}.preview.mp4` → `mark_succeeded(result={object_key,
  preview_key, transcode, codec})`。消费方：`POST /annotation-tasks`(source=video) 用
  `analysis._browser_friendly_video_key` 查最新 succeeded job 换预览 key。**同 signal_ingest
  约定**：自捕获异常 rollback + 重取 job 行写 failed，不重抛；转码跑在 executor 单线程
  轮询内（长视频转码期间其他 job 排队）。

## 坑/限制

- **Session 归属**：每个 handler 拿到的是执行器专用的独立 `Session`（`SessionLocal`，
  `expire_on_commit=False`），**不是**请求 session；handler 自行 commit（进度逐步 commit 让
  轮询可见），失败由 executor 兜底。不要在里面用请求 session 的约定（不 commit）推理。
- **`run_job` 别开两个 session 同时用**：`SessionLocal` 在测试里可能绑同一引擎
  （StaticPool 单连接），两个活跃 Session 抢同一连接会冲突；`run_job` 已改为一个 session
  全程，轮询线程对每个已领 job 各自开一个 session（前一个已 close）。
- **别在 `HANDLERS` 里硬编码调度逻辑**：新增域任务（split/annotation/training...）在本包加
  一个 `xxx.py`，`@register_handler("type")` 注册即可，executor 无需改动。
