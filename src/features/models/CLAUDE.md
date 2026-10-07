# CLAUDE.md — src/features/models/

模型中心（2026-08-29 重构自 App.tsx 抽出）。训练数据准备/模型资产/新建训练/测试评估/推理验证五个子菜单。

## 文件

- `ModelCenter.tsx`：
  - `TrainingDataPreparation`（`model-center/dataset-build`）：`listDatasets` 选数据集 + 来源单选（manual/split_task/annotation_task）→ `createDatasetVersion` 自动 `createBuildTask` + `useJob` → 展示 8:1:1 划分 + 样本总数/质量/快照。**2026-09-28**：原来用 `dataset.status === '可训练'` 拦"生成训练数据版本"（按钮 + 表单整块隐藏），现在**去掉这道门禁**——`dataset.status` 已改为"上一个已构建版本"的适配结论，拿它拦"还没构建过的新版本"会死锁（当前版本不过检 → 不能重建 → 永远不过检）。改为：进入时按 `getReadiness(dataset.id)` 拉一次适配结论，仅作**提示**（`READY_TEXT.failed` 的 `build-blocked` 提示"仍可生成新版本"）；按钮只按 `datasetId != null && buildJobId == null` 禁用。能不能训练由后端准入（val/冻结标注/适配检查）说了算。
  - `ModelRepository`（`model-center/repository`）：`listModels` 汇总（总数/生产候选/最近训练）+ 模型卡片，「新建模型」← `createModel` + `refreshKey` 刷新计数。**标准模型目录常驻**（时序数据缺陷检测/目标检测/熔池分割三张能力入口卡，不再仅空状态显示），目录下方渲染模型卡片网格，无模型时显示空态文案。卡片图标按 `model.type` 经 `MODEL_TYPE_ICONS` 区分（时序分类→Activity、目标检测→Target、语义分割→ScanLine、多模态回归→BarChart3，未识别回退 `Cpu`，组件 `ModelTypeLogo`）。
  - `Training`（`model-center/training`）：`createTrainingTask`（超参读表单 `config`）+ `useJob` → 指标/损失曲线（`lossToPath` SVG path）/日志（`getTrainingLogs`）。`modelMetricText` 把 `metric` dict 转文案。**2026-09-28**：数据集勾选在**明确** `暂不可训练` 时禁用（`selectable = hasTrainingVersion && readiness !== '暂不可训练'`；结论未回来时不拦，避免加载期闪现禁用态），与后端训练准入同一口径（`READY_TEXT` 文案，界面不出现"可训练"字样）。
  - `ModelTestLive`（`model-center/testing`）：`createTestTask` + `useJob` → 指标 + 2×2 混淆矩阵。
  - `InferencePanel`（`model-center/inference`）：上传文件（`uploadFile`<100MB / `presignUpload`≥100MB + PUT，**PUT 后先查 `res.ok`**）→ `createInferenceTask` + `useJob` → 类别/置信度/耗时。
  - `DatasetBuild`：数据集构建（旧入口别名）。

## 调用链

- 被谁调用：`src/App.tsx`（`model-center/*` 五个路由懒加载）。
- 调用谁：`src/api/models`（listModels/createModel/createTrainingTask/getTrainingLogs/createTestTask/createInferenceTask）、`src/api/datasets`（listDatasets/createDatasetVersion/createBuildTask）、`src/api/files`（uploadFile/presignUpload/putFileDirect）、`src/hooks/useJob`、`src/shared/components`（Toolbar）。

## 关键规则/坑

- **训练/测试输入必须是数据集版本**（`dataset_version_id`），不是数据版本号——与 `src/features/versions` 的「数据集版本 vs 数据版本」语义一致（T1 术语）。
- 训练任务由后端真实 Torch CPU 训练驱动（`app/services/torch_training.py` + MLflow 记录，见 `backend/app/services/CLAUDE.md` 与 `backend/app/integrations/CLAUDE.md`）；前端 `lossToPath` 数据驱动画损失曲线，`Training` 的 `listDatasets()[0]` 是 best-effort 默认。
- PUT 后先查 `res.ok`，失败抛错丢弃 object_key（同 Registration 约定）。
- `modelMetricText` 处理 `metric` dict；`Training`/`ModelTestLive`/`InferencePanel` 的成功态均以 Job 轮询为准，错误显示 `job.error.message`。

- **单焊缝划分的显式提示（2026-10）**：`TrainingDataPreparation` 新增 `WithinWeldWarning`——
  `split.strategy === 'within_weld'` 时在结果面板上方给 `build-blocked` 警告
  「本版本按「焊缝内」划分，指标不代表跨焊缝泛化」。只有一条焊缝时后端改为在焊缝内部按时间
  切分（否则 `val=0` 根本训不了），代价就是这个指标口径；**这条提示是护栏的唯一出口，
  别删**。同时把「自动划分规则」的文案从"按**样本**分组"改成"按**焊缝**分组"（原文写错了，
  实际一直是按焊缝分组的），并补一句单焊缝时会退化为焊缝内切分。
  `DatasetSplit` 类型新增可选 `strategy?: 'by_weld' | 'within_weld'`（见 `api/types.ts`）。
