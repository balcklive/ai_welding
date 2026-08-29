# CLAUDE.md — src/features/overview/

数据总览页（首页）。

## 文件

- `OverviewPage.tsx`：`OverviewPage({navigate})`——数据总览仪表盘。`getDashboardData` 内部聚合四个真实接口（`getStats/getAttributes/getDistributions/getProjects`）并带 **5 分钟浏览器缓存**。内部组件 `StatCard`（统计卡）、`DonutChart`（分布环形图）。

## 调用链

- 被谁调用：`src/App.tsx`（`route === 'overview'` 懒加载）。
- 调用谁：`src/api/dashboard.getDashboardData`；`src/app/navigation`（Route）；lucide-react 图标。

## 关键规则/坑

- **总览用浏览器缓存（5 分钟 TTL）**：缓存失效后重新请求并覆盖，避免每次刷新重复打四个接口；**接口失败显示明确错误状态，不使用 mock 兜底**。
- 分布/缺陷 `tone` 用 `donutPalette` 按序取色（后端不输出颜色）；多模态 token 经 `modalityMeta` 映射中文 label/icon/desc。
