# 数据中心工具栏修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-executing-plans to implement this plan task-by-task.

**Goal:** 修复报告导出无可见结果的问题，并让“上传数据”仅在数据集详情页显示。

**Architecture:** 在 `WorkspaceFrame` 与 `DatasetWorkspace` 之间增加详情状态回调；`Toolbar` 只在存在 action 时渲染主按钮，并在点击时同步预留下载窗口、异步填充 URL。继续复用现有 API 和单文件组件结构。

**Tech Stack:** React 18、TypeScript、Vite、Node 内置测试。

## Global Constraints

- 保持 `src/App.tsx` 单文件结构和现有信息架构。
- 不修改后端报告接口、数据登记接口或其他页面行为。
- 导出继续使用 `exportReport({ type, ref_ids, format: 'pdf' })`。
- 使用现有按钮样式，不引入 UI 依赖。

---

### Task 1: Add regression coverage for toolbar behavior

**Files:**
- Modify: `src/App.overview-regression.test.mjs` or create `src/App.toolbar-regression.test.mjs`

- [ ] Step 1: Add static assertions that `WorkspaceFrame` derives a dataset-detail-only action and that `Toolbar` handles the absent action state.
- [ ] Step 2: Add assertions that export code reserves a synchronous popup and visibly exposes an error state.
- [ ] Step 3: Run `node --test src/App.toolbar-regression.test.mjs` and verify the new assertions fail against the current implementation.

### Task 2: Implement dataset-detail-only upload action

**Files:**
- Modify: `src/App.tsx` around `WorkspaceFrame`, `DatasetWorkspace`, and `Toolbar`

**Interfaces:**
- `DatasetWorkspace` accepts `onDetailChange?: (isDetail: boolean) => void`.
- `Toolbar` accepts `action?: string` instead of requiring an action string.

- [ ] Step 1: Add `isDatasetDetail` state in `WorkspaceFrame`, reset it when route is not `data-center/datasets`, and pass the callback to `DatasetWorkspace`.
- [ ] Step 2: Update dataset list/detail transitions to notify false/true respectively; clean up to false on unmount.
- [ ] Step 3: Set the data-center toolbar action only when the route is dataset workspace and detail state is true; keep the existing navigation target.
- [ ] Step 4: Render the primary toolbar button only when `action` is present.

### Task 3: Make report export reliable and visible

**Files:**
- Modify: `src/App.tsx` in `Toolbar`

- [ ] Step 1: Add local `exporting` and `exportError` state; clear errors before each attempt.
- [ ] Step 2: On click, synchronously reserve `window.open('', '_blank')`, then call `exportReport`.
- [ ] Step 3: On success, assign the first returned URL to the reserved window; if popup creation failed, navigate the current window as fallback.
- [ ] Step 4: On missing URL or request failure, close the reserved window and render a visible error message; restore button state in `finally`.

### Task 4: Verify and update project docs

**Files:**
- Modify: `src/CLAUDE.md` if the toolbar behavior note needs updating

- [ ] Step 1: Run `node --test src/App.toolbar-regression.test.mjs src/App.buffer-regression.test.mjs src/vite-base-regression.test.mjs`.
- [ ] Step 2: Run `npm run typecheck` and `npm run build`.
- [ ] Step 3: Run `node /home/pf/.agents/skills/impeccable/scripts/detect.mjs --json src/App.tsx`.
- [ ] Step 4: Review `git diff`, update `src/CLAUDE.md` only if needed, and commit the implementation.
