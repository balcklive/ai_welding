# CLAUDE.md — src/

前端源码（React 18 + TypeScript + Tailwind）。

- `main.tsx`：React 入口，挂载 `App`。
- `App.tsx`：主应用（约 840 行，单文件）。含四个一级模块——数据总览、数据中心、分析与标注、模型中心；实现侧边栏导航、Tab 切换、"先选数据"上下文状态。当前所有数据为演示数据（mock）。
- `index.css`：Tailwind 全局样式。
- `vite-env.d.ts`：Vite 类型声明。
- `api/`：前端接口层（Task 18 起）。`client.ts`（统一 fetch 封装：解包信封、注入 JWT、401 清 token 重载）、`types.ts`（全部实体/请求体类型，契约见 `docs/API接口清单.md`）。详见 `api/CLAUDE.md`。
- `hooks/`：前端 React 钩子层（Task 20 起）。`useJob.ts` 通用异步任务轮询（消费 `api/jobs.getJob`）。详见 `hooks/CLAUDE.md`。
- `pages/`：前端页面层（Task 20 起）。`Login.tsx` 最小登录页（登录成功写 token+user 到 localStorage 并通知外层）。详见 `pages/CLAUDE.md`。

坑/限制：
- `App.tsx` 是单文件大组件，改动时不要破坏现有信息架构（四个模块 + 先选数据模式）。
- `package.json` 里的 `@supabase/supabase-js` 依赖当前未使用。
- 接入后端时：接口走 `src/api/`，相对路径 `/api/v1/...`（契约见 `docs/API接口清单.md`）；开发环境由 `vite.config.ts` 的 `/api` proxy 转发到 `http://localhost:8000`，生产同源。不要重写 `App.tsx`。
