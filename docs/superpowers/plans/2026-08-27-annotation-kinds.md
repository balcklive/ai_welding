# 数据标注升级（时序区间标注 + 视频多边形标注）Implementation Plan

> **For agentic workers:** 按本文档 Task 逐个实现；契约变更以 `docs/` 根五份文档为准，改契约先改文档再同步代码。

**Goal:** 把当前"图像单帧 bbox 目标检测标注"（Task 14，模拟闭环）升级为两类真实标注：

1. **时序标注**：在波形图上点选缺陷起止时间区间 `[start, end]` + 缺陷类型（搭配焊缝图片）；
2. **视频标注**：LabelMe 式在视频帧上画多边形标注熔池区域。

**已敲定技术选型（2026-08-27 用户确认）：**

| 决策点 | 定稿 | 理由 |
|---|---|---|
| 时序波形画布 | **ECharts**（Apache-2.0） | 自带 markArea 区间绘制 / dataZoom 缩放 / crosshair 十字光标，交互工作量最小，符合"复用优先"规则 |
| 视频多边形标注 | **react-image-annotate**（MIT） | LabelMe 式多边形/顶点编辑/缩放/撤销开箱即用 |
| 视频帧来源 | **前端截帧**（标注）+ **后端按时间戳抽帧**（导出/建数据集时） | 标注阶段零后端改动、交互实时；训练数据在后端抽帧保证可靠 |
| 数据模型 | **扩展 `annotations` 表**，`kind` 判别 | 单表加 `kind/points/start_time/end_time`，复用现有"任务→样本→标注"流与端点，改动最小 |

**Architecture:** `Annotation` 表 `kind`（`box` 默认兼容 | `segment` | `polygon`）判别几何类型；`Sample` 用 `meta.mode` 区分锚点（`signal` 信号样本 / `frame` 视频帧 / 默认帧）。时序标注、视频标注都走现有 `POST /annotation-tasks/{tid}/samples/{sid}/labels` 覆盖写端点，前端零新接口。

**Tech Stack:** 后端 FastAPI + SQLModel + Alembic（uv）；前端 React 18 + TypeScript + Vite；新增前端依赖 `echarts`、`react-image-annotate`（标注阶段后端无新依赖，ffmpeg 只进导出/建数据集阶段）。

## Global Constraints

- 改模型字段**三同步**：`alembic` 新迁移 + `docs/数据库设计.md` + `app/models/CLAUDE.md`；改接口同步 `API接口清单.md`。
- 现有 bbox 标注（`kind=box`）与老数据**零破坏**。
- `src/App.tsx` 单文件结构不破坏；标注页改动遵守"只换数据源/加模式，不改现有信息架构"。
- 前端依赖用 `npm i`（前端非 uv 管）；后端 Python 一律 uv。
- ECharts 用裸 `echarts` + 自写薄封装（业务胶水），不引 `echarts-for-react`。

---

## Phase 0：契约与模型

### Task 1: 同步三份契约文档

**Files:**
- Modify: `docs/数据库设计.md`（§3.9 samples meta 说明、§3.10 source 扩展、§3.11 annotations 新列）
- Modify: `docs/API接口清单.md`（§3.4 标注端点 labels 语义扩展 kind）
- Modify: `docs/CLAUDE.md`（已回写差异列表）

- [x] Step 1: §3.11 `annotations` 增列 `kind`（VARCHAR(16) NOT NULL DEFAULT 'box'）、`points`（JSON，polygon 顶点）、`start_time`（DOUBLE，segment 起点秒）、`end_time`（DOUBLE，segment 终点秒）。
- [x] Step 2: §3.9 `samples.meta` 注明 `mode` 取值（signal/frame）；§3.10 `annotation_tasks.source` 注明后续扩展（signal/video）。
- [x] Step 3: `API接口清单.md` §3.4 `POST …/labels` 的 `LabelItem` 加 `kind/points/start_time/end_time`，标注按 kind 分支校验说明。
- [x] Step 4: `docs/CLAUDE.md`"已回写差异"追加本变更。

### Task 2: 后端模型 + 迁移 0007

**Files:**
- Modify: `backend/app/models/analysis.py`（`Annotation`）
- Add: `backend/alembic/versions/0007_annotation_kind.py`
- Modify: `backend/app/models/CLAUDE.md`

- [x] Step 1: `Annotation` 加 `kind`（VARCHAR(16) 默认 `box`）、`points`（JSON nullable）、`start_time`（Double nullable）、`end_time`（Double nullable）；`box` 保留。
- [x] Step 2: 迁移 `0007` 加 4 列（`kind` NOT NULL `server_default='box'`，其余 nullable），down_revision=`0006`（链 0005→0006→0007→0008 线性）。
- [x] Step 3: `app/models/CLAUDE.md` 同步 §3.11 新列。

## Phase 1：时序标注

### Task 3: 后端 kind 校验 + save_labels 透传 + 序列化

**Files:**
- Modify: `backend/app/api/v1/analysis.py`（`LabelItem`、`save_annotation_labels`）
- Modify: `backend/app/services/annotation.py`（`save_labels`、`annotation_payload`）

- [x] Step 1: `LabelItem` 加 `kind: str = "box"`、`points: list | None`、`start_time: float | None`、`end_time: float | None`（`box` 改可选）。
- [x] Step 2: 路由校验按 `kind` 分支：`box`→`len==4`；`segment`→`start_time/end_time` 有限且 `0<=start<end`；`polygon`→`points` ≥3 个 `[x,y]` 顶点；未知 kind→400。
- [x] Step 3: `save_labels` 透传新字段到 `Annotation` 行；`annotation_payload` 序列化 `kind/points/start_time/end_time`。
- [x] Step 4: 补 `tests/test_split_annotation.py`：segment/polygon 保存与回读、非法 kind/区间/顶点 400（含 signal 来源锚点样本测试）。

### Task 4: 前端时序标注模式（ECharts）

**Files:**
- Modify: `src/App.tsx`（`Annotation` 组件新增时序模式；复用 `getSignals`）
- Add: `src/hooks/useECharts.ts`（薄封装）
- Modify: `src/api/analysis.ts` / `src/api/types.ts`（`Annotation` 加新字段；signal 样本获取）

- [x] Step 1: `types.ts` `Annotation` 加 `kind/points/start_time/end_time`；`LabelItem` 同步。
- [x] Step 2: 标注页新增"时序标注"面板（`AnnotationSignal`）：ECharts 实例 + 四通道波形（`getSignals(dataId, String(versionId), {})`）+ `dataZoom` 缩放。
- [x] Step 3: 交互：点击设起点 → 再点设终点 → 选缺陷类别 chip → 生成区间；区间/草稿/异常段用 `markArea` 着色。
- [x] Step 4: 侧栏区间列表（`[start–end] + 缺陷类型`，可删）；波形旁配焊缝图片（`getVersion` object_keys → `getFileUrl`）。
- [~] Step 5: AI 提示 = `signal_ingest` 真实 `anomalies` 区间渲染为图表色带（未做「一键转 segment 标注」；异常类型与缺陷类别词表不同，转换需用户确认）。

## Phase 2：视频多边形标注

### Task 5: 后端 polygon 保存 + 视频帧锚点

**Files:**
- Modify: `backend/app/services/annotation.py` / `backend/app/api/v1/analysis.py`（polygon 校验已在 Task 3，这里补视频锚点 Sample 来源）
- Modify: `backend/app/core/seed.py`（可选：新增"熔池"标签类别）

- [ ] Step 1: `label_categories` 新增"熔池"类别（语义分割单类）。
- [ ] Step 2: 视频帧锚点：`Sample(meta.mode='frame', meta.timestamp)` 的导入/创建路径（复用 `import` source=files 或新增 source=video）。

### Task 6: 前端视频标注模式（react-image-annotate）

**Files:**
- Modify: `src/App.tsx`（标注页新增视频模式）
- Modify: `package.json`（新增 `react-image-annotate`）

- [ ] Step 1: 自建 `<video>` 播放器 + 帧导航（播放/暂停/上一帧/下一帧/时间轴）。
- [ ] Step 2: 暂停时 `canvas.drawImage` 取当前帧 `toDataURL` → 喂 `react-image-annotate` 画多边形。
- [ ] Step 3: 保存 `{timestamp: video.currentTime, points, category:'熔池'}` → `POST …/labels`（kind='polygon'）。
- [ ] Step 4: 已标注帧在时间轴做标记点，可跳回编辑。

## Phase 3：标注数据消费（训练导出）

### Task 7: 后端导出抽帧 + 掩膜生成

**Files:**
- Modify: `backend/app/services/datasets.py` / 新增导出 helper
- Modify: `Dockerfile`（新增 ffmpeg，仅本阶段）

- [ ] Step 1: 建数据集/导出时，按 `Annotation(kind='polygon')` 的 `timestamp` 用 ffmpeg 抽帧 + 多边形填充生成掩膜 PNG 写 MinIO。
- [ ] Step 2: 时序 segment 标注导出为 JSON 标签文件（与信号样本对齐）。

## Task 8: 验证与收尾

- [ ] Step 1: 后端 `cd backend && uv run pytest` 全绿。
- [ ] Step 2: 前端 `npm run typecheck && npm run build` 通过。
- [ ] Step 3: 三份契约 + 各层 CLAUDE.md 全部同步，`git diff` 复查后提交。
