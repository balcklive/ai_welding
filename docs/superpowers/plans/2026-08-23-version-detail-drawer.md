# Version Detail Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-subagent-driven-development (recommended) or supo-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make weld and dataset version “查看” buttons open an API-backed detail drawer.

**Architecture:** Add a reusable `VersionDetailDrawer` in `src/App.tsx` with `weld` and `dataset` variants. Each owner component controls selected version state and supplies close behavior; API data is loaded by the drawer with mock-free loading/error states. Add focused static regression assertions because the project has no component test runner.

**Tech Stack:** React 18, TypeScript, lucide-react, Vite, Node built-in tests.

## Global Constraints

- Keep the existing single-file `src/App.tsx` information architecture.
- Use `src/api/` for API calls and preserve existing mock fallback behavior.
- Do not expose secrets or change backend contracts.
- Update `src/CLAUDE.md` when changing the frontend script behavior.

---

### Task 1: Regression test for version view behavior

**Files:**
- Modify: `src/App.buffer-regression.test.mjs`

- [x] Add assertions that `VersionPanel` renders `VersionDetailDrawer`, passes `mode="weld"`, and wires the clicked version id; add equivalent assertions for `DatasetDetail` with `mode="dataset"`.
- [x] Run `node --test src/App.buffer-regression.test.mjs` and confirm it fails because the handlers/components do not exist yet.

### Task 2: API-backed reusable drawer

**Files:**
- Modify: `src/App.tsx`

- [x] Import `getVersion`, `getValidation`, and `getDatasetVersion`.
- [x] Add `VersionDetailDrawer` with typed props for weld/dataset modes, loading state, error state, Escape handling, and close button.
- [x] Render weld identity, metadata, note, object keys, and validation summary; render dataset snapshot identity, counts, split, quality, and snapshot id.
- [x] Add `version-drawer` styles and responsive behavior in `src/index.css`.
- [x] Run the focused regression test and confirm it passes.

### Task 3: Wire both version lists

**Files:**
- Modify: `src/App.tsx`

- [x] Add selected version state to `DatasetDetail`; attach `onClick` to non-current dataset version buttons and render the dataset drawer.
- [x] Add selected version state to `VersionPanel`; attach `onClick` to every version button and render the weld drawer.
- [x] Ensure click handlers stop row propagation where applicable and current-version status remains non-clickable.
- [x] Update `src/CLAUDE.md` with the new drawer behavior.
- [x] Run typecheck, lint, build, and the focused regression test.
