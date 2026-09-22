# CLAUDE.md — src/features/annotation/segment/

分段样本**段级标注**工作台（2026-09-22）。路由 `analysis/sample-annotation`，侧边栏「分析与标注 → 分段样本标注」。

与上层 `annotation/` 目录里那套几何标注（图像框 / 时序区间 / 视频多边形）是**两条独立的标注线**——
本目录只做 v3 分段样本的**段级分类**：一个 `Sample`（时间窗）= 一个主结论（正常 / 缺陷 + 主缺陷类别）。

设计/实施说明见 `docs/分段样本标注设计与实施说明.md`；契约 `docs/API接口清单.md` §3.9。

## 文件

- `SampleAnnotationWorkspace.tsx`：唯一组件，含三部分。
  - **入口**：`listAnnotatableTasks(weldId)` 列出该焊缝**已完成 + v3** 的分段任务（带进度），选一个进入
    工作台。没有可标注任务时给明确引导（先去「样本分段」生成）。
  - **样本列表（左）**：分页拉取（`PAGE_SIZE=50`）、`全部 / 未标注` 筛选、进度条、缺陷分布、
    上一段 / 下一段（**页边界自动翻页**，靠 `pendingSelectRef` 把选中项带到新页）。
  - **样本详情（右）**：三模态 —— 局部波形（`LocalWave`，横轴按该段自身起止）+ 视频（seek 到
    `t_video = t_signal − offset`）+ 焊缝图片切片；每个模态带 `ModalityTag`（可用 / 未标定 / 不可用 + 原因）。
  - **结论表单**：正常 / 缺陷切换 + 类别网格（含已停用的历史类别）+ 备注 + 保存 / 保存并下一段 / 撤销。

## 调用链

- 被谁调用：`src/App.tsx`（路由 `analysis/sample-annotation` 懒加载；需 `selectedDatasetId + selectedDataId`，
  否则显示 `SelectionRequired`）。入口按钮也在 `features/alignment/split/SplitRulesPanel.tsx`（分段成功后出现）。
- 调用谁：`src/api/sampleAnnotations`（工作台全部读写）、`src/api/analysis.getSplitSample`（样本的三模态细节）、
  `src/api/files.getFileUrl`（视频 / 切片预签名）、`src/features/analysis/signals/chartData`（`chanColorOf`）、
  `src/features/alignment/split/splitTypes`（`timePath`/`trackRange`/`fmtRange` 纯函数）、`src/shared/components`。

## 关键规则/坑

- **三模态共用一个窗**：时间范围只来自该 `Sample` 的 `start_time`/`end_time`。**不要**做成"每个模态
  各自可标注 / 各自时间轴"——那正是本期要避免的歧义（见设计说明 §4）。
- **模态缺失不阻断标注**：未标定 / 无视频 / 图片裁切失败都只显示原因（`ModalityTag`），表单始终可用。
- **词表只读**：候选来自 `GET /segment-annotation/categories`；增删改在「系统设置 → 分段样本缺陷词表」
  （`settings/options/defect_category`）。历史标注显示的是**写入当时的名称快照**，不要回查词表去"修正"。
- **切到「正常」必须清空已选类别**（`categoryId: null`），避免残影提交；「缺陷」未选类别时保存按钮禁用。
- **详情与结论是两个请求**（`getSplitSample` + `getSegmentAnnotation`）：样本的模态信息有它自己的主人
  （§3.4），这里不复制一份。未标注时 `annotation=null` 是**正常状态**，不是 404。
- **保存后必须重新拉当前页**：`未标注` 筛选下当前行会从列表消失，所以"保存并下一段"用**保存前的下标**
  定位下一段（`indexBefore`），不能按新列表里找当前 id。
- **不要在这里清 `pendingSelectRef`**：翻页正是靠它把选中项带到新页，它由 `[rows]` 效果消费后自清。
- 读操作失败置错误态（`tasksError`/`listError` + 重试），**不回落 mock**（全站禁令）。
