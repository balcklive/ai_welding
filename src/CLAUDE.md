# CLAUDE.md — src/

前端源码（React 18 + TypeScript + Tailwind）。

- `main.tsx`：React 入口，挂载 `App`。
- `App.tsx`：主应用（约 840 行，单文件）。含四个一级模块——数据总览、数据中心、分析与标注、模型中心；实现侧边栏导航、Tab 切换、"先选数据"上下文状态。当前所有数据为演示数据（mock）。
- `index.css`：Tailwind 全局样式。
- `vite-env.d.ts`：Vite 类型声明。

坑/限制：
- `App.tsx` 是单文件大组件，改动时不要破坏现有信息架构（四个模块 + 先选数据模式）。
- `package.json` 里的 `@supabase/supabase-js` 依赖当前未使用。
- 接入后端时：新建 `src/api/` 目录封装请求，接口用相对路径 `/api/...`；不要重写 `App.tsx`。
