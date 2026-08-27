# 统一数据集总览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-executing-plans to implement this plan task-by-task.

**Goal:** 将总览页统一使用“数据集”术语，最多展示两行卡片，并提供跳转全部数据集列表的入口。

**Architecture:** 仅修改 `Overview` 的展示层：将 API 返回的项目卡片截取前 6 条，标题区新增导航按钮，使用已有 `navigate('data-center/datasets')` 路由。数据接口和数据中心页面保持不变。

**Tech Stack:** React 18、TypeScript、现有 CSS、Node 内置静态回归测试。

## Global Constraints

- 保持现有信息架构、API 调用和视觉样式不变。
- 两行按现有三列布局计算，最多显示 6 个数据集。
- 使用现有 Route 类型和 navigate 回调，不新增路由。

---

### Task 1: 修改总览数据集展示

**Files:**
- Modify: `src/App.tsx` 中 `Overview`
- Test: `src/App.overview-regression.test.mjs`

- [ ] **Step 1: 写失败的静态回归测试**

断言 `Overview` 源码包含“数据集”文案、最多 6 条切片和 `data-center/datasets` 跳转，同时不再包含“数据项目”标题文案。

- [ ] **Step 2: 运行测试确认失败**

Run: `node --test src/App.overview-regression.test.mjs`
Expected: FAIL，因为当前仍使用“数据项目”且没有 6 条限制和全部数据集按钮。

- [ ] **Step 3: 实现最小修改**

在 `Overview` 中将 `filteredProjects` 映射改为 `filteredProjects.slice(0, 6)`，标题改为“数据集”和“共 X 个数据集”，并添加按钮：

```tsx
<button className="ghost-button" onClick={() => navigate('data-center/datasets')}>
  查看全部数据集 <ArrowUpRight size={14} />
</button>
```

- [ ] **Step 4: 运行测试和构建**

Run: `node --test src/App.overview-regression.test.mjs && npm run build`
Expected: 测试通过，生产构建成功。

- [ ] **Step 5: 运行 Impeccable 检测**

Run: `node /home/pf/.agents/skills/impeccable/scripts/detect.mjs --json src/App.tsx`
Expected: 无本次修改引入的严重问题。

- [ ] **Step 6: 提交修改**

```bash
git add src/App.tsx src/App.overview-regression.test.mjs docs/superpowers/plans/2026-08-26-unify-dataset-overview.md
git commit -m "feat: unify overview dataset terminology"
```
