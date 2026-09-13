# CLAUDE.md — src/features/overview/

数据总览页（首页）。

## 文件

- `OverviewPage.tsx`：`OverviewPage()`——数据总览仪表盘。`getDashboardData` 内部聚合三个真实接口（`getStats/getAttributes/getDistributions`）并带 **5 分钟浏览器缓存**。内部组件 `StatCard`（统计卡）、`DonutChart`（分布环形图）。

## 调用链

- 被谁调用：`src/App.tsx`（`route === 'overview'` 懒加载）。
- 调用谁：`src/api/dashboard.getDashboardData`；`src/shared/components/PageIntro`；lucide-react 图标。

## 关键规则/坑

- **总览用浏览器缓存（5 分钟 TTL）**：缓存失效后重新请求并覆盖，避免每次刷新重复打三个接口；**接口失败显示明确错误状态，不使用 mock 兜底**。
- **无底部「数据集卡片」区（2026-09-14 删除）**：总览页原本在图表下方渲染 `section-title` + `dataset-grid` 的数据集卡片（`查看全部数据集` → `data-center/datasets`、`查看详情` → `analysis/select`），现已整体移除——总览页不再接收 `navigate` prop（`App.tsx` 直接渲染 `<OverviewPage />`），后端 `GET /dashboard/projects` 与前端 `getProjects()` 封装同步删除。**总览页不提供数据集入口**，数据集改由侧边栏「数据管理 / 数据集」进入；勿再在总览页恢复该区块（回归断言见 `src/App.overview-regression.test.mjs`）。
- 分布/缺陷 `tone` 用 `donutPalette` 按序取色（后端不输出颜色）；多模态 token 经 `modalityMeta` 映射中文 label/icon/desc。
