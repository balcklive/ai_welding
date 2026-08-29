# CLAUDE.md — src/pages/

前端页面层（契约：`docs/API接口清单.md` §4.3）。当前进度：**Task 20**（最小登录页 `Login.tsx`）。后续接入页面（总览/数据管理/分析/模型中心）逐步落位，UI 仍由 `src/App.tsx` 的单文件大组件承载（勿重构）。

## 脚本

- `Login.tsx`：最小登录页（默认导出 `Login`，无 UI 库）。
  - Props：`{ onSuccess?: () => void }`——登录成功（token + user 已落 localStorage）后由外层回调切换渲染（`App.tsx` 用它 `setToken(getToken())` 让闸门放行）。
  - 表单：用户名 + 密码两个输入 + 提交按钮 + 错误提示（`role="alert"`）。前端空值校验「请输入用户名和密码」。
  - 提交：`auth.login(username, password)`（**`skipAuth: true`**——密码错误是业务失败，不会触发 client 的「401 → 清 token + 重载」，登录页得以展示错误）。
  - 成功 → `client.setToken(res.access_token)` 写 localStorage（key=`token`，后续请求由 client 自动注入 `Authorization`）+ 存 `res.user`（key=`user`，JSON 串，供侧边栏用户卡等消费；`LoginResult` 已含 user，**无需再调 `auth.getMe`**）→ 调 `onSuccess`。
  - 失败 → 仅 `setError(err.message)`（`ApiError` 的 message 即信封 message，如「用户名或密码错误」），**不刷新页面**。
  - 样式：复用 index.css 现有 `primary-button`；登录特有布局用文件内 `<style>`（类名前缀 `login-`，如 `.login-page`/`.login-card`/`.login-input`/`.login-error`），不污染全局样式、不引 UI 库。
  - 视觉：深底 `#102d35` 居中卡片，品牌标为 `/logo-mark.png`（`data/logo.png` 裁圆标去字版，黑底已转透明；由 `scripts/make_logo_assets.py` 生成）+ ForgeLab，与 App 侧边栏一致。

## 坑 / 限制

- **不引 UI 库、不动 `index.css` 全局**：登录样式只在文件内 `<style>` 作用域内，类名带 `login-` 前缀防冲突。
- 刷新会话恢复：App 闸门直接读 localStorage `token`（`getToken()`）；若需用 `auth.getMe` 校验 token 有效性/刷新 user，属后续增强，勿在登录页重复调。
- 本目录为新目录，新增页面时同步更新本文件。
