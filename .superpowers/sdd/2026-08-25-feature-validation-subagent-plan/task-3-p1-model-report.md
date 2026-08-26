# Task 3 P1 分析、特征、数据集与模型验证报告（纠正重测版）

- 执行时间：2026-08-25 17:19–17:31（本地）
- 环境：`http://127.0.0.1:8000/api/v1`、`http://127.0.0.1:5173/ai_welding/`、MySQL、MinIO、`backend/logs/api.log`
- 方法：**API + DB + MinIO + 前端代码审计**。本次未把任何页面交互结果记为 PASS；凡属于页面观测项，均明确标注为 **API-only** 或直接判 `BLOCKED/FAIL`。
- Job 判定统一规则：**仅轮询而后台未自动消费的任务，不计 PASS；`run_job()` 只作诊断。**
- 结果汇总：**PASS 31 / FAIL 16 / BLOCKED 2**
- 总体状态：**FAIL**

## 全局纠正结论

1. **旧报告编号错位已全部作废**；本版严格按清单一项一号重写。
2. **当前 live 库存在更广泛 schema 漂移**：
   - `data_versions` 缺 `request_key`
   - `split_tasks` 缺 `request_key` / `active_request_key`
   - `alignment_tasks` 缺 `request_key` / `active_request_key`
3. **后台 Job 执行器在 live 环境未自动消费新建任务**。本次新建的 `signal_ingest / dataset_build / training / test / inference` 均在连续轮询中保持 `pending`。
4. **推理临时文件生命周期未闭环**：已推理完成的 `uploads/*` 仍可经预签名 URL 读取。

---

## SIG-001..008 高级信号分析

| 编号 | 状态 | 结果 |
|---|---|---|
| SIG-001 | PASS | `GET /welds/WLD-20260825-0003/versions/22/signals` 返回 4 通道 `cur/vol/gas/wir`。 |
| SIG-002 | PASS | `psd/stft/dwt/wavelet/phase/pdd` 六个 mode 全部 `200`。 |
| SIG-003 | PASS | `analysis/psd?channel=cur` 与 `channel=vol` 返回频谱明显不同；`signals?channels=cur&channels=vol` 仅返回两通道。 |
| SIG-004 | PASS | `signals` 对 `低通/高通/带通` 均返回 `200`；低通前后同一 `cur` 通道前 10 点已变化。 |
| SIG-005 | PASS | 非法带通 `cutoff>=cutoff2`、未知 mode、未知 channel 均返回 `400`。 |
| SIG-006 | PASS | `WLD-20260825-0003/v1.0(id=22)` 返回 `source=real`；`WLD-20260815-0248/v1.3(id=4)` 返回 `source=generated`。 |
| SIG-007 | FAIL | 补测 4 个子案例：`missing_channel / all_empty / short / irregular_fs`。4 个 `signal_ingest` Job 连续轮询均停留 `pending`；手动 `run_job()` 后统一失败于 schema 漂移：`Unknown column 'data_versions.request_key'`。随后 `signals` 接口又回退到 `generated`，页面若只看接口将看到伪造的 4 通道成功数据，不能算通过。 |
| SIG-008 | PASS（API-only） | `src/api/analysis.ts::decimate()` 明确把通道点数抽稀到 `<=512`；对 `WLD-20260815-0248/v1.3` 实测原始 `cur` 长度 `5420`，按同算法复核为 `512`。未做浏览器帧率证明。 |

## FEAT-001..006 特征提取

| 编号 | 状态 | 结果 |
|---|---|---|
| FEAT-001 | PASS | `POST /features/extract` 成功返回 `ts_features + vision_features + audio_features + unified_vector`。 |
| FEAT-002 | PASS | `Min-Max/CSV` 输出值域为 `[0,1]`；`L2/PT` 输出范数约 `1.0`。 |
| FEAT-003 | PASS | 统一向量总维度 `42`；7 个 group 连续覆盖 `[0,42)`。 |
| FEAT-004 | PASS | 同一版本同参数重复提取返回新 `id`，但 `unified_vector.values` 完全一致。 |
| FEAT-005 | PASS | 以当前提取记录 `feature_extraction.id=6` 执行 `POST /reports/export {type:'features', ref_ids:[6], format:'json'}`，返回 URL 的 `ref_id=6`；取回 JSON 后 `ref_id=6`，且 summary 中版本/归一化/格式与本次提取一致。 |
| FEAT-006 | FAIL | 对缺模态版本 `WLD-20260825-0004/v1.0(id=33)` 仍直接提取成功并返回 `42` 维统一向量，无“缺失/回退”标识，也未拒绝。 |

## DATASET-001..010 数据集创建和版本

| 编号 | 状态 | 结果 |
|---|---|---|
| DATASET-001 | PASS | 新建目标检测数据集成功：`T3-det-31b687bf` → `DS-DEFECT-016`。 |
| DATASET-002 | PASS | 新建 `图像分类 / 时序分类 / 多模态质量预测` 3 类数据集均成功；后两类被分配 `DS-GEN-*` 编号，说明后端接受但未做专门类型体系。 |
| DATASET-003 | FAIL | `GET /datasets/{id}` 可返回 `sample_count/status/quality`，但**没有标签分布字段/接口**；“查看标签分布”无法完成。 |
| DATASET-004 | PASS（API-only） | `GET /datasets/1/versions` 返回 `split={train:6736,val:842,test:842}`；`GET /datasets/14/versions/14` 返回 `split={train:2,val:0,test:0}`。 |
| DATASET-005 | PASS（DB） | 对 `dataset_version_id=14` 查询 `dataset_items+samples`，同一焊缝仅落入 `train`，未见跨 split 泄漏。 |
| DATASET-006 | BLOCKED | `POST /datasets/1/versions` 可创建新固定版本占位 `v1.4(id=17)`，但本次未能在“源数据变化后”重建并比较固定清单；`dataset_build` Job 自动消费失败，无法完成“旧快照不随源数据变化”闭环证明。 |
| DATASET-007 | FAIL | 旧版本 `v1.3(id=1)` 仍可 `GET 200`；但新版本 `v1.4(id=17)` 的 `dataset_build` Job 连续轮询始终 `pending`，旧版本“可查看”成立、但“新版本复现”未完成，因此整项失败。 |
| DATASET-008 | PASS | `GET /datasets/14/lineage` 返回 4 层：`records(1)` → `annotation_tasks(1)` → `dataset_versions(2)` → `training_tasks(2)`，血缘链存在。 |
| DATASET-009 | FAIL | `GET /datasets/15/readiness` 为 `暂不可训练`，但 `POST /training-tasks {dataset_version_id:15}` 仍返回 `200 + job_id`，服务端未拦截。 |
| DATASET-010 | BLOCKED | `GET /datasets/*/dimensions` 确实会展示 `已具备/缺失/必需` 三态；但本次未构造出“仅缺可选模态、必需模态齐全”的 live 数据版本，无法严谨判定“允许继续训练”是否成立。 |

## MODEL-001..006 模型仓库

| 编号 | 状态 | 结果 |
|---|---|---|
| MODEL-001 | PASS | `GET /models` 与 `GET /models/1` 正常；模型详情返回完整版本列表。 |
| MODEL-002 | PASS | 新建模型成功：`T3-model-31b687bf`。 |
| MODEL-003 | PASS | 同名再次创建返回 `409`。 |
| MODEL-004 | PASS | `PATCH /models/1/versions/5` 可在 `实验版本 ↔ 生产候选` 间切换；非法状态 `已上线` 返回 `400`。 |
| MODEL-005 | PASS | 训练成功样例 `job_5a7edaed` 返回 `model_version.id=5, model_id=1`；DB 中对应 `training_tasks.dataset_version_id=14`，模型版本、训练任务、数据集版本关联成立。 |
| MODEL-006 | PASS | `models/5/weights.pt` 可通过 `/files/{key}/url` 取到预签名地址并成功下载，`Content-Length=37`。 |

## TRAIN-001..008 模型训练

| 编号 | 状态 | 结果 |
|---|---|---|
| TRAIN-001 | PASS（API-only） | 可选择并提交固定数据集版本：`POST /training-tasks {dataset_version_id:1}` 返回 `200 + job_id`。 |
| TRAIN-002 | PASS | 训练参数 `epochs=2,batch_size=8,learning_rate=0.002,val_ratio=0.3` 可提交；诊断完成后 `GET /training-tasks/job_60b0af69/logs` 明确回显这些参数。 |
| TRAIN-003 | FAIL | 新建训练任务 `job_accdf7b2 / job_60b0af69` 连续轮询均为 `pending`，后台未自动消费。 |
| TRAIN-004 | PASS | 诊断执行后的 `GET /training-tasks/job_60b0af69` 返回 `metrics + loss_curve`；`GET /training-tasks/job_60b0af69/logs` 返回逐 epoch 日志。 |
| TRAIN-005 | PASS | 诊断执行后训练成功自动生成 `model_version.id=7, model_id=8, file_key=models/7/weights.pt`。 |
| TRAIN-006 | FAIL | 通过 DB 注入坏超参 `hyperparams={'epochs':'oops'}` 创建训练任务 `job_4f0b1723`。自动轮询阶段仍停 `pending`；手动 `run_job()` 后虽能进入 `failed` 且错误消息清晰，但根据统一 Job 规则，本项不能 PASS。 |
| TRAIN-007 | PASS（API-only） | 对已完成任务 `job_60b0af69` 连续两次 `GET /training-tasks/{id}`，状态、指标、版本号完全一致，说明刷新恢复已落库。 |
| TRAIN-008 | FAIL | 同一数据集版本连续两次 `POST /training-tasks` 均返回不同 `job_id`（`job_94c913a9`、`job_262001f0`），无防重复。 |

## TEST-001..005 模型测试

| 编号 | 状态 | 结果 |
|---|---|---|
| TEST-001 | FAIL | 有效请求 `POST /test-tasks {model_version_id:1,dataset_version_id:1}` 可创建 `job_fb690ad8/job_9f503427`，但连续轮询始终 `pending`，未自动执行。 |
| TEST-002 | PASS | 诊断执行后 `GET /test-tasks/job_9f503427` 返回 `accuracy/recall/F1/latency_ms/confusion_matrix`。 |
| TEST-003 | FAIL | 不匹配组合 `model_version_id=1 + dataset_version_id=2(语义分割)` 仍返回 `200 + job_id`，无版本适配校验。 |
| TEST-004 | FAIL | 无测试集版本 `dataset_version_id=14`（`split.test=0`）仍返回 `200 + job_id`，未拦截。 |
| TEST-005 | PASS | 对测试任务 DB id `5` 执行 `POST /reports/export {type:'test', ref_ids:[5], format:'json'}` 成功；取回 JSON 后 summary 正确引用 `模型版本=1, 数据集版本=1`。 |

## INFER-001..006 模型推理

| 编号 | 状态 | 结果 |
|---|---|---|
| INFER-001 | FAIL | 图片上传成功（`uploads/.../valid_weld.jpg`），但新建推理任务后连续轮询始终 `pending`；仅手动 `run_job()` 才成功。 |
| INFER-002 | FAIL | 视频上传成功（`uploads/.../valid_weld.mp4`），但视频推理任务 `job_2675e4fa` 连续轮询始终 `pending`；仅手动 `run_job()` 才成功。 |
| INFER-003 | PASS | 诊断执行后推理结果稳定返回 `categories/confidence/latency_ms`；图片、视频、损坏文本三种诊断任务都能取到该结构。 |
| INFER-004 | FAIL | 破坏性补测：损坏 JPG、`text/plain` 伪装图片都可创建并成功完成推理；只有 `101MB` 超大文件上传被 `/files/upload` 正确拒绝 `400`。整项失败。 |
| INFER-005 | FAIL | 对同一图片 object key 连续两次 `POST /inference-tasks` 均返回不同 `job_id`（`job_cc1a8e53`、`job_ad5700b0`），无去重。 |
| INFER-006 | FAIL | 证据 1：上传与推理文件统一位于 `uploads/`；证据 2：推理完成后 `valid_weld.jpg / valid_weld.mp4 / t3_bad.txt` 仍可通过预签名 URL 读取，未见生命周期清理。 |

---

## 主要 concerns

1. **schema 漂移扩大**：旧报告已发现 `split_tasks/alignment_tasks` 缺字段；本次新增确认 `data_versions.request_key` 也缺失，直接打断 `signal_ingest`。
2. **Job 自动消费失效是 Task 3 最大阻塞面**：`signal_ingest / dataset_build / training / test / inference` 全受影响。
3. **服务端业务闸门不足**：`DATASET-009 / TEST-003 / TEST-004 / INFER-004 / TRAIN-008 / INFER-005` 全是“前端可能提示、后端仍放行”。
4. **推理上传区缺清理策略**：`uploads/*` 可长期残留，且可重复推理。
5. **本版没有把任何“页面应受影响”写成 PASS**；页面项只在 API-only 证据足够时给结论，否则直接 FAIL/BLOCKED。

---

## 附录 A：旧报告事实保留与修正映射

### A.1 旧 SIG 编号错位 → 新编号

- 旧 `SIG-001`（六种分析 mode）→ **应为 `SIG-002`**
- 旧 `SIG-002`（四通道查看）→ **应为 `SIG-001`**
- 旧 `SIG-003`（real/generated source）→ **应为 `SIG-006`**
- 旧 `SIG-004`（通道切换）→ **应为 `SIG-003`**
- 旧 `SIG-005`（滤波联动）→ **应为 `SIG-004`**
- 旧 `SIG-006`（非法参数）→ **应为 `SIG-005`**
- 旧 `SIG-007`（前端抽稀上限）→ **应为 `SIG-008`**
- 旧 `SIG-008`（analysis/result 稳定）→ **不属于当前清单编号，已移除**

### A.2 旧 FEAT / DATASET 错位说明

- 旧 `FEAT-005` 实际写成“非法参数返回 400”，**不对应本清单任何 FEAT 编号**，已移除；本版 `FEAT-005` 改为真实补测“导出特征集并核对当前提取记录引用”。
- 旧 `DATASET-001..006` 大量写成 `annotation_task / split_task / manual / filter` 四种构建来源测试，**并不对应清单中的 001..006**；这些旧事实仅作为环境观察保留，不再占用编号。

### A.3 旧报告中经本次复测仍成立的事实

- Job 自动消费失效：**仍成立**，且影响面比旧报告更大。
- `uploads/` 生命周期未闭环：**仍成立**。
- 缺模态特征提取仍直接成功：**仍成立**。
- 测试版本不匹配 / 无测试集仍放行：**本次补测确认成立**。
- 训练/推理双击防重复：**本次补测确认失败**。

---

## 修复 subagent 追加记录（2026-08-25）

### 变更摘要

1. **特征提取**：`POST/GET /features` 新增 `modality_status`，对缺失视觉/音频模态显式标注 `fallback`，不再把缺模态结果伪装成“完整真实特征”。
2. **数据集详情 / 训练闸门**：`GET /datasets/{id}` 新增 `label_distribution`；训练创建前按 **指定 dataset_version** 做 readiness 校验，`暂不可训练` 直接 400 拒绝；同时补测“仅缺可选模态、必需输入齐全”仍可训练。
3. **测试/推理/幂等**：
   - `POST /test-tasks` 新增模型-数据集兼容性校验与 `test split` 校验。
   - `POST /training-tasks` 对同一 `dataset_version` 的活动任务去重。
   - `POST /inference-tasks` 对同一 `model_version + input_key + input_type` 幂等；新增真实文件校验（损坏/伪装图片、gif 等不支持格式、>100MB 输入拒绝）。
4. **uploads 生命周期**：`/files/upload` 与落在 `uploads/` 前缀的 `/files/presign-upload` 响应新增 `lifecycle={policy:temporary, retention_days:30, prefix:'uploads/'}`，按现有 OSS 设计给出**可验证的 30 天临时保留策略**，未承诺立即删除。
5. **自动 executor / 固定快照 / 在线迁移回归**：补充后台自动消费 `signal_ingest / dataset_build / training / test / inference` 回归；补充固定版本快照与旧版本复现回归；在线 Alembic 回归扩展到 `data_versions.request_key`、`split_tasks/alignment_tasks request_key/active_request_key`。

### RED / GREEN 命令输出

- RED
  - `uv run pytest tests/test_features.py::test_extract_features_marks_fallback_modalities -q` → `FAILED KeyError: 'modality_status'`
  - `uv run pytest tests/test_datasets.py::test_dataset_detail_includes_label_distribution -q` → `FAILED KeyError: 'label_distribution'`
  - `uv run pytest tests/test_models.py::test_training_rejects_unready_dataset ... test_inference_deduplicates_same_input_key -q` → `6 failed`（训练 readiness 未拦截、training/inference 未幂等、test 缺校验、推理文件未校验）
  - `uv run pytest tests/test_files.py::test_upload_small_file -q` → `FAILED KeyError: 'lifecycle'`
- GREEN
  - 上述定向用例重跑全部通过。
  - `uv run pytest tests/test_models.py tests/test_datasets.py tests/test_features.py tests/test_files.py -q` → `70 passed`
  - `uv run pytest -q` → `248 passed`
  - `uv run pytest tests/test_models.py::test_auto_executor_consumes_training_test_and_inference_jobs tests/test_datasets.py::test_auto_executor_consumes_dataset_build_job tests/test_signal_ingest.py::test_auto_executor_consumes_signal_ingest_job tests/test_datasets.py::test_fixed_snapshot_old_version_remains_reproducible tests/test_models.py::test_alembic_upgrade_online_real_path_executes_0003 -q` → `5 passed`
  - `npm run typecheck` → `tsc --noEmit` 通过
  - `npm run build` → Vite build 通过（有既有 Browserslist 过期提示）

### 在线迁移执行结果（试验库）

- 迁移前：`uv run alembic current` → `0002`
- 执行：`uv run alembic upgrade head`
- 迁移后：`uv run alembic current` → `0004 (head)`
- schema 核对：
  - `data_versions`：`request_key` 存在，`uq_data_versions_record_action_req` 存在
  - `alignment_tasks`：`request_key` / `active_request_key` 存在，唯一约束为 `uq_alignment_tasks_active_request_key`
  - `split_tasks`：`request_key` / `active_request_key` 存在，唯一约束为 `uq_split_tasks_active_request_key`

### commit hash

- implementation commit: `3bb81ac5e10ac429c61455f94dcc94bf05e14bbc`
