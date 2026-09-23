# CLAUDE.md — src/features/annotation/segment/

分段样本**段级标注**工作台。路由 `analysis/sample-annotation`，侧边栏「分析与标注 → 分段样本标注」。

与上层 `annotation/` 目录里那套几何标注（图像框 / 时序区间 / 视频多边形）是**两条独立的标注线**——
本目录只做 v3 分段样本的**段级分类**：一个 `Sample`（时间窗）= 一个主结论（正常 / 缺陷 + 主缺陷类别）。

设计/实施说明见 `docs/分段样本标注设计与实施说明.md`；契约 `docs/API接口清单.md` §3.9。

## 文件

- `SampleAnnotationWorkspace.tsx`：工作台（入口 + 状态编排 + 时间轴渲染）。
  - **入口**：`listAnnotatableTasks(weldId)` 列出该焊缝**已完成 + v3** 的分段任务（带进度）。
    **默认只显示最近一次成功的那一个**（服务端按 `SplitTask.id desc` 返回，`tasks[0]` 即它）；
    同焊缝用**别的窗口规则**切出来的历史任务折叠在「历史分段任务（N）」里，展开才渲染。
    理由：分段任务的去重键是 `(version_id, rules, task_format)`，改一次窗口参数就多一个任务；
    两批混着标，数据集构建会拿到两套口径的样本。这条是「同一焊缝没有权威分段任务」这个
    设计缺口的**前端兜底**——真正的指针（哪一批是 current）仍待后端补。
    没有可标注任务时给明确引导（先去「样本分段」生成）。
    **删除**：每张卡右侧有独立删除按钮（不是塞进卡片里——按钮套按钮是无效 HTML，破坏性操作
    混进"进任务"的点击区里也容易误触），走 `ConfirmDialog`（`tone="danger"`）二次确认后调
    `deleteSplitTask`。失败时**不关弹窗**——后端的拒绝原因（任务还在跑 / 样本已进数据集快照）
    要留在用户眼前。
  - **全局条**：整条焊缝一窗一格（格宽 = 该段时长占焊缝总时长的比例），绿=正常 / 红=缺陷 /
    灰=未标注。点击任意一格直接选中该窗（所在批次随之切换）。
  - **批次**：`BATCH_SIZE = 20`。批次由**选中项反推**（`batchIndex = ⌊选中下标 / 20⌋`），
    不另存批次号——翻批、点全局条、按 ←/→ 全都只是"改选中项"，不存在两个状态要对齐。
  - **时间轴**：标尺 + 信号泳道 + 焊缝图片带 + 视频帧轨 + 标注行，横轴是**批次局部时间**
    （`x = t − batchFrom`）。信号轨道经 `clipTrack` 裁到批次——`timePath` 会把越界时刻钳到
    两端，不裁就会画出一条假的水平线。
  - **保存/撤销**：用响应里的 `{annotation, progress}` **原地改那一列**，不重拉整个时间轴
    （全量窗口已在内存，旧稿"保存后重拉列表 + 用保存前下标兜圈子"的复杂度随之消失）。
- `AnnotationRail.tsx`：右栏。**结论表单在上**（总览已回答了"这一段长什么样"，右栏第一职责是
  把结论定下来），下面是本窗三模态细节的"放大版"（本窗局部波形 / 播放器 / 焊缝切片大图）。
  同文件内含 `VerdictDraft` 类型、`StatusTag`、`ModalityTag`、`LocalWave`、`EmptyRail`。

## 调用链

- 被谁调用：`src/App.tsx`（路由 `analysis/sample-annotation` 懒加载；需 `selectedDatasetId + selectedDataId`，
  否则显示 `SelectionRequired`）。入口按钮也在 `features/alignment/split/SplitRulesPanel.tsx`（分段成功后出现）。
- 调用谁：`src/api/sampleAnnotations`（`getAnnotationTimeline` 拿总览 + 读写结论）、
  `src/api/analysis.getSplitSample`（**本窗**局部时序，总览不给这一份）、
  `src/api/files.getFileUrl`（视频预签名；帧图与切片图的时间轴端点已给 URL，不重复签）、
  `src/features/alignment/split/SignalTimelineLane`（信号泳道，props 是纯的，直接喂）、
  `src/features/alignment/split/splitTypes`（`fmtRange`/`pctOf`/`timePath`/`trackRange`）、
  `src/shared/components`。

## 关键规则/坑

- **窗口与边界一律来自服务端**：`GET /split-tasks/{id}/annotation-timeline` 读的是**已落库的
  `Sample`**（不是按规则重算）。前端只做批次切片与坐标换算，**不复制任何切分算术**。
- **全量的是索引，不是媒体**：窗口索引/标注态一次拿全，但**只有当前批次挂 `<img loading="lazy">`**。
  这是设计文档 §4 硬约束 3 在总览口径下的细化，改这里等于推翻该约束。
- **标注行不依赖任何模态**：勾/叉那一行永远渲染。图/视频取不到只让对应胶片轨走空态——
  结论来自人工判断，不能被某个模态的缺失挡住。
- **三模态共用一个窗**：不要做成"每个模态各自可标注 / 各自时间轴"。
- **切到「正常」必须清空已选类别**（`categoryId: null`），避免残影提交；「缺陷」未选类别时保存按钮禁用。
- **词表只读**：候选来自 `GET /segment-annotation/categories`；增删改在「系统设置 → 分段样本缺陷词表」
  （`settings/options/defect_category`）。历史标注显示的是**写入当时的名称快照**，不回查词表去"修正"。
- **详情与结论是两个请求**（`getSplitSample` + `getSegmentAnnotation`）。未标注时 `annotation=null`
  是**正常状态**，不是 404。
- **快捷键**：`←/→` 换窗口、`N` 标正常并保存、`D` 进缺陷态。焦点在 `input/textarea/select/button`
  上时一律放行——否则打字时的方向键会被吞掉。`N` 用**当场构造的那一份草稿**提交，不等 `setDraft` 落地。
- **`VideoTimelineLane` 刻意没有复用**：本目录的胶片轨（`SampleAnnotationWorkspace.tsx` 里的
  `FilmLane`）要承载标注态着色、且要渲染两份（焊缝图片 + 视频帧）；合并的代价是给分段页那条轨
  加一堆可选 props，再加一层把 `AnnotationTimelineWindow` 伪装成 `SplitPreviewWindow` 的适配层。
  分段页那条轨被 `App.split-lanes-regression.test.mjs` 逐条钉着，不要去动它。
- **信号轨道的纵轴量程按批次自适应**（`trackRange` 取裁切后的值）——与分段页（整条焊缝量程）
  不同。翻批时波形幅度会变，那是本批次的真实动态范围，不是信号跳变。
- 读操作失败置错误态（`loadError`/`detailError` + 重试），**不回落 mock**（全站禁令）。
