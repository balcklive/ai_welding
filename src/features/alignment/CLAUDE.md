# CLAUDE.md — src/features/alignment/

分析与标注·多模态对齐（标定层）+ 样本分段工作台。

## 文件

- `AlignmentWorkspace.tsx`：**多模态对齐 · 时间轴对齐工作室**（**2026-10**：对齐版本 = `selectedVersionId ?? 最新版`，上下文条选了版本就对齐那一版；对齐成功后 `setSelectedVersionId(alignRes.version.id)` **回写全局**，产物版本其他页也要看得到）。`studio-ruler` 共享时间标尺 + 各模态 `lane` 轨道 + 模态勾选 → `createAlignmentTask`；`listVersions` 找 v1.0 → `getFileUrl` 渲染 `<video>`、`getSignals(v1.0)` 画真实波形；`getCalibration` 取标定（offset 供播放器 seek 换算、`seam_image` 供 ROI 面板回显）；ROI 保存走 `handleSaveRoi` → `updateCalibration({seam_image: {roi} | {excluded:true}})`（**本页是全站唯一能改 ROI 的地方**）；成功/失败横幅（`event_source`/`job.error.message`）。内部件：`AvailabilityTag`、`SeamRoiEditor`、常量 `VIDEO_EXTS`/`ALIGN_CHANNEL_MAP`/`ALIGN_TRACK_META`。
- `SeamRoiEditor.tsx`：**焊缝图片 ROI 标定面板**（2026-09-23）。真实照片上拖拽框选 → 按 `naturalWidth/Height` 把鼠标位置换算回**原始像素**（ROI 是像素坐标，不是归一化值）→ `PUT …/calibration`（越界由服务端比图片宽高拒绝，错误原样显示）；「不对焊缝图片进行分段」写 `excluded: true`。**不写 ROI 的框（draft）绝不影响产出**——分段页与正式任务只认已保存的那份。
- `VideoFilmLane.tsx`：**统一轴上的视频胶片条（可拖，2026-10）**。把视频画成统一轴上**真实占位的一段**：`left = offset`、`width = videoDuration`，拖它改 offset（往右拖 offset 变大）。**为什么要有这条轨**：此前"视频的时间 bar"是 `<video controls>` 的原生进度条，量程是视频自己的 0–duration，与信号轴**没有任何几何关系**——两条 bar 叠在一起看起来能对上、实际对不上。拖动**全程零网络**（帧内容与 offset 无关，服务端只按视频时刻抽一次帧），松手才保存。要点：① 位置/宽度用**不钳**的局部 `axisPct`——`AlignmentWorkspace.pct` 与 `splitTypes.pctOf` 都 `Math.min(100, Math.max(0,…))`，拿它们算会说谎（offset 超出信号时时条粘最右、视频比信号长时宽封顶 100%，把"超出"藏起来），越界交给 `.lane-track{overflow:hidden}` 如实裁掉；② 像素→秒用**轨道**宽（`timelineDur / trackWidth`），不是条宽（条短于轨道时会过量移动）；③ 起弧磁吸是**双条件**阈值（≤14px **且** ≤0.5s——纯 px 阈值在长信号上会大得离谱：646px 轨道 + 182s 信号 → 14px ≈ 3.9s）并带迟滞（释放 24px）；④ 手势三件套：`setPointerCapture` + `pointerId` 过滤 + `up`/`cancel` 都清拖动态，`preventDefault` + `draggable={false}` 挡原生图片拖拽，`dx≈0` 不算改动；⑤ 抽帧全失败但时长已知时**仍画条、仍可拖**（条宽只靠时长，不靠帧），无帧的格走 `.film-cell-empty` 不顶替。配套后端 `GET …/video-frames`（见 `backend/app/services/CLAUDE.md`）。
- `OffsetCalibrationPanel.tsx`：**视频零点偏移标定面板**（2026-10）。补上设计 §12.6 缺的那一半（此前 offset 只有 `PUT` 接口、页面无入口）。三件事：① **反向标定**「以当前帧对齐起弧」——用户把播放器停在画面刚起弧那一帧点一下，父组件按 `offset = events.arc − video.currentTime` 反解（后端语义 `t_video = t_signal − offset` 的反解），不必猜数值；② 数值输入 + 滑块手填（滑块 ±10s 仅供粗调，更大的值走数字框，后端护栏 ±3600）；③ **时间戳对照读数**——「视频当前帧 ↔ 换算信号时刻」+ 覆盖残差 `offset + videoDuration − signalDuration`，|残差| > 0.5s 提示「零点可能未对齐」。**是受控组件**（草稿由父组件持有，因为 offset 要即时驱动 `<video>` seek），自身**不发任何网络请求**——写入仍只有父组件一条路径。
- `split/`：**样本分段工作台（v3）**，见 `split/CLAUDE.md`。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/alignment` → `AlignmentWorkspace`；`analysis/split` → `split/SplitWorkspace`）。
- 调用谁：`src/api/analysis`、`src/api/welds`、`src/api/files`、`src/hooks/useJob`、`src/shared/components`、`../analysis/signals/chartData`。

## 关键规则/坑

- **`splitOnly` 双形态已删除（2026-09-22，v3）**。分段不再是 `AlignmentWorkspace` 的一个变体，而是独立工作台 `split/SplitWorkspace`；本页只负责"建立统一坐标系"（标定）。**不要再把切分规则塞回这一页**——历史上出过"点创建切分任务实跑对齐任务"的错位。
- **职责边界（§4.1）**：本页 = 标定层（offset / ROI / 焊接速度来源，产出 mapping + 新版本）；分段页 = 切分层（只读标定，改时长/步长、预览、生成样本）。
- **视频 seek 必须成对换算**：seek 写 `currentTime = Math.max(0, t - effectiveOffsetRef.current)`，`onTimeUpdate` 写回 `playhead = currentTime + effectiveOffsetRef.current`。只改一处，seek 后游标会被立刻拨回原位。
- **点击定位的委托选择器必须同时排除视频预览轨与胶片轨（2026-10）**：`closest('.studio-ruler, .lane-track:not(.lane-track-video):not(.lane-track-film)')` —— **两处都要**（`closest` 判定 与 `querySelectorAll` 补 `tabindex`/`role`）。漏掉 `:not(.lane-track-film)` 的话点一下胶片条会**既改 offset 又 seek**，而且会把胶片轨标成 `role="slider"` 却没有键盘行为（假可及性）。这是本轮最容易漏、后果最直观的一条，`App.alignment-film-lane-regression.test.mjs` 钉着。
- **视频拆成两条轨（2026-10）**：胶片条（`VideoFilmLane`，统一轴上可拖 = 对齐用）与「视频预览」（播放器，看细节）。**不能把播放器留在胶片条同一条轨里**——原生 `<video controls>` 的手势会和拖动抢；一条轨只表达一件事（同 `split/VideoTimelineLane.tsx` 的取舍）。
- **拖动时的 seek 走 rAF 合并**（`scheduleSeek`）：pointermove 是 ~60Hz，每次都写 `currentTime` 会疯狂 seek 掉帧。**只有画面的 seek 被节流**，读数（`effectiveOffset`）照旧即时更新。
- **偏移量的"实时预览"是 ref 而不是 state 依赖（2026-10）**：`effectiveOffset = videoOffsetDraft ?? videoOffset`（草稿优先），同步进 `effectiveOffsetRef`，两处换算都读 ref。**不要把 `videoOffset` 放回 click 委托 effect 的依赖数组**——那样每拖一格滑块就重挂一次监听器（并重跑 `querySelectorAll().setAttribute`）。`alignRes`/`videoUrl` 留在依赖里是有意的：新出现的 `.artifact-row` 要补 tabindex/role。
- **拖偏移要带着画面一起走**（`handleOffsetDraft`）：草稿一变就把 `<video>` seek 到 `playhead − 新偏移` 并钳在 `[0, duration]`。这是设计 §4.2「拖动 offset 时同屏游标与视频画面同步移动，用户对准起弧时刻即可」——只改读数不动画面，"对比时间戳"就只剩数字，没法目视对准。游标还没落点（`playhead <= 0`）或视频未就绪时不 seek，只更新读数。
- **标定 UI 两半都落地了（ROI 2026-09-23 / offset 2026-10）**：焊缝图片 ROI 框选在 `SeamRoiEditor`（左键拖拽是唯一手势，无缩放手柄，倾斜焊缝的旋转矩形仍留后续）；视频零点偏移在 `OffsetCalibrationPanel`（反向标定 + 数值/滑块）。**offset 面板挂在 `alignment-aside` 顶部**——aside 是 `.alignment-board` 的**兄弟**，所以点击不会冒进 board 上挂的 seek 事件委托；**别再把它挪进 board 里**。
- **`videoTime`/`videoDuration` 取自 `<video>` 元素自身**（`onTimeUpdate` / `onLoadedMetadata`），不取对齐产物 `metadata`——未跑过对齐就没有产物，而这两个值本就该是"用户此刻在拖的那个视频"的真值（反向标定用同一元素，两者自洽）。换版本/换焊缝时随 `setVideoUrl(null)` 一起清零，否则读数会显示上一个视频的值。
- **换算后的信号时刻可能为负，不能喂 `fmt()`**（2026-10 实机踩到）：`t_signal = t_video + offset`，offset 为负或偏移超过视频当前位置时它就是负数。而 `analysis/signals/chartData` 的 `fmt()` 是按**非负时间轴**写的（ruler / 分段页用），`fmt(-5)` 会算成 `Math.floor(-5/60) === -1`、余数 `55` → 渲染出 `-1:55.00`，`fmt(-0.0017)` → `-1:60.00`。面板内用局部 `timecode()`（保留负号 + 先按显示精度取整，`-0.001 → -0` 不印负号）；**不要为了这个去改 `fmt()`**。回归测试钉住了这一点。
- **"未标定"必须可达**：保存 `offset=0` 也算已标定（`aligned = available && calibrated`），所以给了「清除标定」按钮写 `{video: null}`；否则保存过一次 0 之后系统就一直声称视频已对齐，且状态再也回不去。
- **滑块已删（2026-10）**：偏移的主操作是**拖胶片条**（`VideoFilmLane` → `handleOffsetDraft`）；面板只剩数字框（填已知偏差）与「以当前帧对齐起弧」（覆盖"视频从焊缝中间开始录"这种磁吸表达不了的情况）。别再把它加回来——滑块 ±10s 的行程表达不了"条在轴上的位置"。
- **「不参与分段」与「还没框 ROI」必须在服务端分开**（`calibration.seam_image.excluded`）：两者都让图片模态在预览/manifest 里记 `available=false`，但**原因与引导不同**——前者不该再催用户去标定。只把 ROI 清成 `null` 会把前者显示成后者，所以不参与走 `excluded`、不清 ROI；想回到"未标定"才用 `{seam_image: null}` 清空整组。
- 对齐/切分 Job 用 `useJob` 轮询；需先选焊缝（`selectedDatasetId + selectedDataId`），否则 `SelectionRequired`。
