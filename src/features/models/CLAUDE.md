# CLAUDE.md — src/features/models/

模型中心（2026-08-29 重构自 App.tsx 抽出）。训练数据准备/模型资产/新建训练/测试评估/推理验证五个子菜单。

## 文件

- `ModelCenter.tsx`：
  - `TrainingDataPreparation`（`model-center/dataset-build`）：`listDatasets` 选数据集 + 来源单选（manual/split_task/annotation_task）→ `createDatasetVersion` 自动 `createBuildTask` + `useJob` → 展示 8:1:1 划分 + 样本总数/质量/快照。
  - `ModelRepository`（`model-center/repository`）：`listModels` 汇总（总数/生产候选/最近训练）+ 模型卡片，「新建模型」← `createModel` + `refreshKey` 刷新计数。
  - `Training`（`model-center/training`）：`createTrainingTask`（超参读表单 `config`）+ `useJob` → 指标/损失曲线（`lossToPath` SVG path）/日志（`getTrainingLogs`）。`modelMetricText` 把 `metric` dict 转文案。
  - `ModelTestLive`（`model-center/testing`）：`createTestTask` + `useJob` → 指标 + 2×2 混淆矩阵。
  - `InferencePanel`（`model-center/inference`）：上传文件（`uploadFile`<100MB / `presignUpload`≥100MB + PUT，**PUT 后先查 `res.ok`**）→ `createInferenceTask` + `useJob` → 类别/置信度/耗时。
  - `DatasetBuild`：数据集构建（旧入口别名）。

## 调用链

- 被谁调用：`src/App.tsx`（`model-center/*` 五个路由懒加载）。
- 调用谁：`src/api/models`（listModels/createModel/createTrainingTask/getTrainingLogs/createTestTask/createInferenceTask）、`src/api/datasets`（listDatasets/createDatasetVersion/createBuildTask）、`src/api/files`（uploadFile/presignUpload/putFileDirect）、`src/hooks/useJob`、`src/shared/components`（Toolbar）。

## 关键规则/坑

- **训练/测试输入必须是数据集快照**（`dataset_version_id`），不是焊缝版本号——与 `src/features/versions` 的「数据集快照 vs 焊缝版本」语义一致。
- 训练任务由后端真实 Torch CPU 训练驱动（`app/services/torch_training.py` + MLflow 记录，见 `backend/app/services/CLAUDE.md` 与 `backend/app/integrations/CLAUDE.md`）；前端 `lossToPath` 数据驱动画损失曲线，`Training` 的 `listDatasets()[0]` 是 best-effort 默认。
- PUT 后先查 `res.ok`，失败抛错丢弃 object_key（同 Registration 约定）。
- `modelMetricText` 处理 `metric` dict；`Training`/`ModelTestLive`/`InferencePanel` 的成功态均以 Job 轮询为准，错误显示 `job.error.message`。
