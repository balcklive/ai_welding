# CLAUDE.md — .bolt/

Bolt 工具的项目配置目录，无业务脚本。

- `config.json`：模板声明（`bolt-vite-react-ts`）。
- `prompt`：UI 设计约束。要点：
  - 用 Tailwind + React hooks + lucide-react 图标；除非必要，不额外安装 UI 主题/图标库。
  - 组件导入用 `@/` 路径别名（映射到 `src/`），避免深相对路径如 `../../components/...`。

坑/限制：改动 UI 前先读此文件；其中约束了技术选型，不要随意引入新 UI 库。
