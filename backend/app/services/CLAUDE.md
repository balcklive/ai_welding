# CLAUDE.md — backend/app/services/

业务服务层：跨域复用的领域逻辑。当前进度：Task 7（通用 Job 服务）+ Task 8（Dashboard 总览聚合查询）+ Task 10（Welds 核心 CRUD）+ Task 11（真实 DSP + 确定性信号生成）+ Task 12（多模态特征提取）+ Task 13（多模态对齐模拟）+ Task 14（标注服务）+ Task 15（数据集服务）+ Task 16（模型中心服务）+ **Task 17（通用报告导出）**。

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
- `welds.py`：**Task 10**。焊缝核心 CRUD，供 `app/api/v1/welds.py` 路由调用（契约 §3.3）。
  提供：业务号生成器（`next_weld_id`/`next_registration_no` = 当日前缀计数+1 零填充、
  `next_version_no` = 同焊缝最大次版本+1）；`create_registration`（事务内 record+v1.0+
  latest 联动，modalities=[]/quality=待复核/operator=调用方）；`list_welds`（服务端筛选+
  分页：`q` LIKE weld_id/registration_no、`source`/`brand` 前缀、`status` 精确、
  `tab` 映射 待核验→待复核 / 已归档→通过 / 最近·全部→仅排序）；版本链/新建版本；
  `run_validation` = **15 项确定性核验引擎**（规则名照抄 seed/App.tsx，结果只依赖版本
  `object_keys` 与登记工艺参数，无随机；score=max(0,100-警告*5-失败*20)；质量级联
  失败>0→异常 / 仅警告→待复核 / 否则→通过）；`attach_raw_files`（去重追加 keys +
  累加 storage_bytes + 按扩展名推导回填 modalities，video 含图像）；`list_through_welds`
  （quality=通过 的可分析焊缝，供 analysis candidates）。payload 序列化在
  `record_payload`/`records_payload`（批量预查 latest 版本防 N+1）/`version_payload`/
  `validation_payload`。
- `dsp.py`：**Task 11**。真实 DSP 纯函数（输入 np 数组 + fs，输出 JSON 安全结构）：
  `filter_signal`（butter(4)+sosfiltfilt 零相位，kind 低通/高通/带通，cutoff 为 0~1 归一化
  频率相对奈奎斯特，带通需 cutoff<cutoff2<1）；`compute_psd`（scipy welch →
  `{freqs,psd}`）；`compute_stft`（scipy stft → `{times,freqs,magnitude(2D)}`，幅度 |Z|）；
  `compute_dwt`（pywt wavedec → `{bands:[D1..Dn], approx:A_n}`）；`wavelet_decomp`
  （wavedec 各层细节 → `{bands:[L1..Ln]}`，L1 高频）；`phase_trajectory`（降采样 ≤2048 点）；
  `pdd_density`（复刻 App.tsx PddChart 直方图 + 高斯 KDE，counts 之和 == 样本数）。
  全部 numpy→list 走 `.tolist()`。坑：`sosfiltfilt` 要求输入 ≥31 点；wavedec 返回
  `[cA_n, cD_n, …, cD_1]`，即 `coeffs[0]` 是最末层近似、`coeffs[level]` 是 D1。
- `signals.py`：**Task 11**。`generate_signals(weld_id, sample_rate=1000) -> SignalBundle`——
  确定性生成 4 通道（cur/vol/gas/wir，量程与 App.tsx 一致）焊接信号，形态复刻 App.tsx
  currentAmp/voltVal/gasVal/wireVal（起弧 ramp → 稳态 → 收弧 ramp + 两个异常区段低频
  正弦噪声），duration 5.42s、events `{arc:0.42, weld_segment:[0.78,4.28], tail:4.86}`、
  anomalies `[1.92,2.34 电弧不稳, 3.58,3.86 飞溅倾向]`。`analysis_result(bundle)` 返回确定性
  模拟结果（stability≈96.8、segments 由异常时长占比算出）。**坑：种子用 `zlib.crc32(weld_id)`，
  不要用内置 `hash()`——Python 对 str 的 hash 每次进程随机（PYTHONHASHSEED），跨进程不可复现。**
- `features.py`：**Task 12**。多模态特征提取（真实计算，非罐头数字），供 `POST /features/extract`：
  `ts_features(x, fs=1000)` 8 维（均值/方差/峰值/偏度/峰度/RMS + FFT 主频 + 小波细节能量）；
  `vision_features()` 8 维（合成熔池掩膜 → skimage regionprops 几何 4 + graycomatrix GLCM
  纹理 4 + Sobel 梯度，rng=42 确定性）；`generate_audio(weld_id)` 确定性合成电弧音频
  （22.05kHz，crc32 种子 + 固定偏移）+ `audio_features(x, fs)` 6 维（librosa 质心频率/频谱滚降/
  过零率 + scipy welch 频带能量/功率/总 PSD）；`unify(ts, vis, audio, normalization, format)`
  拼 42 维统一向量并归一化（Z-Score/Min-Max/L2/无，零方差/零范数退化保护），返回
  `{total_dims, groups, normalization, format, values}`。**坑：** 气体/送丝分组只取 6 个统计
  特征（对齐 App.tsx 8+8+6+6+4+4+6=42）；FFT 主频依赖 fs（默认 1000）；Sobel 用 float 图
  （uint8 会被 skimage 缩到 0~1）；skimage 0.26 用 `axis_major_length`/`intensity_mean` 新 API；
  未知归一化抛 ValueError（路由先白名单校验）；librosa 懒加载（包导入慢）。
- `alignment.py`：**Task 13**。`simulate_alignment(session, task, job)` 多模态对齐模拟
  （编排真、内核演示，实施边界 §3.1）：进度逐步 0→100（逐次 `session.commit()` + 小睡，
  轮询可见）→ 由任务 modalities（缺省取所属焊缝登记 modalities）推导 `tracks`/`assets`
  （`processed/{weld_id}/align/...`）→ 同事务新建「时间对齐」`DataVersion`（v1.<n+1>、
  operator=算法任务，经 `welds.create_version` 并更新 `latest_version_id`）→ 回填
  `alignment_tasks.events/tracks/assets` → `mark_succeeded(job, result)`。`events` 常量
  `ALIGN_EVENTS={arc:0.42, weld_segment:[0.78,4.28], tail:4.86}` 与 `signals.py` 生成器一致。
  **坑**：本服务里 `session.commit()` 是执行器专用 session 场景（非请求 session 的
  "只 flush 不 commit" 约定）；缺已知模态兜底 `video` 轨道。
- `annotation.py`：**Task 14**。标注服务（编排真、内核演示，实施边界 §3.1）：
  `simulate_annotation(session, task, job)`（handler 领域逻辑：进度逐步 → source=split_task
  时把该切分任务样本 `annotation_task_id` 指向本任务 → `mark_succeeded(job,
  {source,name,samples_count})`）；`resolve_annotation_task` / `resolve_split_task`
  （**job_uid / DB id 双兼容**：先 `get_job_by_uid` 且 type 匹配才认，再按 int 查表，前端
  创建后只拿 job_id 即可直用）；`list_label_categories`（模型口径 5 类）；
  `import_samples`（files 建 `Sample` 行 / split_task 改归属）；`list_samples`（分页 +
  **批量预查 annotations 防 N+1**）；`get_sample` / `get_sample_detail`（样本须属于该任务）；
  `pretag_sample`（**确定性**模拟 2 区域，seed=`random.Random(sample_id)`，替换现有标注，
  annotator=AI预标注）；`save_labels`（**覆盖写**删旧插新，annotator=当前用户，confidence
  缺省沿用先前同类别值）；payload 序列化 `annotation_payload` / `sample_payload`。
  **confidence 语义（契约 §3.4）**：每条 `Annotation` 自带 confidence；样本级
  `_sample_confidence` = 当前标注置信度均值（无标注 → None）。写操作（import/pretag/
  save_labels）**不 commit**（路由提交）；`simulate_annotation` 内的 commit 是执行器专用
  session 场景。
- `datasets.py`：**Task 15**。数据集服务，供 `app/api/v1/datasets.py` 路由调用（契约 §3.5）：
  - `next_dataset_no` = `DS-{类别}-{全局序号}`（类别 DEFECT/POOL/QUALITY 对齐 seed，序号 =
    全库数据集数 + 1，避免与 seed 的全局序号 001/002/003 撞号）；`get_dataset_by_identifier`
    兼容 DB id / dataset_no。
  - `list_datasets`（批量预查当前版本防 N+1）/ `create_dataset`（同名抛 ValueError → 路由 409）/
    `dataset_payload`；`get_dimensions` = 7 项输入维度 `{name, status(已具备|必需|缺失), required}`
    （照 App.tsx inputDimensions/requiredByTask，可用性由当前版本样本 object_keys 启发式判定）；
    `get_readiness` = `{readiness, checks:[{name, passed}]}`（照 App.tsx ModelReadiness，全过 → 可训练）。
  - `list_versions` / `create_version`（下一版本号 v1.<n>）/ `version_payload`；
    **`name`/`note` 仅接受不落库**（`dataset_versions` 表 §3.15 无对应列）。
  - `run_build`（构建 handler 领域逻辑）：来源 gather（annotation_task/split_task/manual/filter）→
    空则兜底合成样本（覆盖全部登记焊缝各 `_SYNTH_PER_RECORD` 个）→ 按 record_id 分组 →
    稳定 seed=42 打乱组序 → 8:1:1（组数 <3 退化为 train / train+test，不泄漏）→ 落
    `dataset_items` → 计算 quality（repeat_rate/empty_label_rate/dimension_missing_rate）→
    快照 JSON 写 MinIO `datasets/{version.id}/snapshot.json`（**尽力而为**，失败仅告警）→
    回填 version + dataset（current_version_id/sample_count/status 可训练）。
    **坑（review 修复）**：quality 的 `dimension_missing_rate` 必须用**本次构建的 in-flight
    samples**（`_dimension_availability_from_samples`）判维度——`datasets.current_version_id`
    在 quality 计算之后才回填，按当前版本查样本会让首次构建的维度缺失率恒为 1.0。
  - `get_lineage` = 4 层节点：原始焊缝 / 标注任务 / 数据集版本 / 模型训练。
  - 解析辅助 `_sample_record_id`：样本 → 所属焊缝（meta.record_id > meta.weld_id > split_task/
    annotation_task→version→record），按焊缝分组划分的依据。
  - **坑**：完整构建来源（type + 各 id）由创建时随 `Job.result={"source":...}` 携带
    （`dataset_build_tasks.source` 仅 VARCHAR(32) 存类型，契约 §3.22）；`_build_snapshot` 内
    延迟 `from app.storage import get_storage`，测试 monkeypatch `app.storage.get_storage`；
    `run_build` 内的进度 commit 是执行器专用 session 场景（同 alignment）。

- `models.py`：**Task 16**。模型中心服务，供 `app/api/v1/models.py` 路由调用（契约 §3.6）：
  - `create_model`（同名抛 ValueError → 路由 409）/ `list_models`（**汇总 + 列表**：summary
    `{total, prod_candidates, recent_training, gpu_usage=42}`，单条查询取全部 model_versions
    按 id 倒序取每条模型最新版本，避免 N+1）/ `get_model`（详情 + 版本列表）/
    `model_payload` / `version_payload`。
  - `update_version_status`（PATCH：status 白名单 生产候选/训练中/实验版本 校验抛 ValueError；
    **note 无对应列仅接受不落库**，同 dataset_versions.name/note 约定）。
  - `run_training`（训练 handler 领域逻辑）：进度逐步 → 确定性指标（mAP50≈0.94-0.96 /
    precision≈0.96 / recall≈0.93，seed=`random.Random(f"train-{task.id}")`）+ 损失曲线
    （train/val 数组长度=epochs，训练损失递减、验证略高）→ **同事务生成 `model_versions`
    （version_no next、status=实验版本、metric、file_key=`models/{id}/weights.pt`）→ 权重
    占位写 MinIO 尽力而为**；`base_model_id` 给定时新版本挂到其所属模型，否则自动新建
    `Model`（name=`训练模型-{task.id}`）；回填 training_tasks.metrics/loss_curve →
    job.result `{metrics, loss_curve, model_version}`。
  - `run_test`（测试 handler）：metrics `{accuracy 0.968, recall 0.942, f1 0.955, latency_ms 18}`
    + confusion_matrix `[[612,18],[22,596]]`（照 App.tsx ModelTest）。
  - `run_inference`（推理 handler）：确定性 boxes/categories/confidence/latency_ms
    （seed=`f"infer-{task.id}"`，3 个预测框、类别取自 焊瘤/气孔/未熔合）。
  - `training_logs(task, job)`：确定性训练日志文本（初始化 → 每 epoch loss/val_loss →
    完成/等待）。
  - 内部助手：`next_model_version_no`（取该模型最大 (major,minor) → `v{major}.{minor+1}`；
    空 → v1.1）、`_recent_training`（最近一次已完成训练 finished_at ISO 串）、`_write_weights`
    （延迟 `from app.storage import get_storage`，测试 monkeypatch 该引用，同 dataset 快照）。
- `reports.py`：**Task 17**。通用报告导出（契约 §3.7 / OSS §2，PDF=Jinja2+xhtml2pdf 复用项）。
  `export_reports(session, type, ref_ids, fmt)` → 每个 ref_id 装配内容 dict → json 直接落
  `reports/{type}/{ref_id}.json` / pdf 渲染 `app/templates/reports/` 模板后写 `.pdf` →
  `upload_stream` + `presign_get` → 返回 `[{ref_id, url}]`。类型 builder：
  `validation`（validation_reports + rule_results 完整模板）、`data-list`（**`ref_ids=[]` → 全量
  单份 ref_id=`all`；非空 → 逐标识 DB id/weld_id/registration_no 解析过滤**）、`features`
  （feature_extractions 统一向量 + 三类特征）、`test`（test_tasks.metrics + 混淆矩阵）、
  `annotation`（annotation_tasks + 样本 COUNT）、`analysis`（数据版本 + signals 确定性分析结果），
  analysis/annotation/features/test 复用 `generic.html.j2`（summary + sections，无数据占位）。
  错误语义：未知类型/格式抛 `ValueError` → 路由 400；`EntityNotFoundError` → 404；写 MinIO
  失败直接抛（导出必须拿到 URL，与 dataset/weights 的"尽力而为跳过"不同）。存储延迟导入
  （`from app.storage import get_storage`，测试 monkeypatch）；时间序列化复用 `jobs._iso_utc`。

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
