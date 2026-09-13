# CLAUDE.md — src/features/settings/

系统设置页（侧边栏底部「系统设置」入口，路由 `settings`）。**新建/管理类页面，不依赖「先选数据」上下文**，与 `data-center/registration` 一样不进 `routesRequiringData`。

## 文件

- `SettingsPage.tsx`：`SettingsPage()` —— 可选项字典管理页。按后端 `OPTION_GROUPS` 返回的分组依次渲染 6 个面板（数据厂家/焊机型号、焊接方法、数据来源、产品/项目信息、数据集任务类型、标注缺陷类别），每组支持：
  - **新增**（输入框 + 新增按钮，Enter 提交，空值禁用）；
  - **改名**（行内输入，Enter 保存 / Esc 取消，只影响后续录入，不回填历史数据）；
  - **停用 / 启用**（`active` PATCH，停用项仍在设置页可见并标「已停用」）；
  - **上移 / 下移**（`POST …/move`，后端整组重排 `sort_order`）；
  - **删除**（行内二次确认 → `DELETE`，按后端返回的 `mode` 提示：`deleted` 物理删 / `deactivated` 因被历史数据引用转为停用）。
  写操作后**重新拉取全量分组**（不做局部合并，避免排序/停用态漂移），串行执行（`pending` 单值 + 全组按钮禁用）。

## 调用链

- 被谁调用：`src/App.tsx`（`route === 'settings'` 时 `React.lazy` 渲染）；侧边栏 `sidebar-bottom` 的「系统设置」按钮 → `navigate('settings')`。
- 调用谁：`src/api/settings`（listOptionGroups / createOptionItem / updateOptionItem / moveOptionItem / deleteOptionItem）、`src/api/client`（`ApiError` 取后端文案）、`src/shared/components/PageIntro`、`src/shared/components/StatusPill`。

## 关键规则/坑

- **写操作仅管理员**：后端对 POST/PATCH/DELETE 做 `is_admin` 校验，非管理员返回 403（`40300`）。前端不预判角色，直接把后端 message 原样展示（`role=alert`），不做静默/假成功。
- **删除语义不猜**：`DELETE` 的 `mode` 由后端按引用情况决定，前端只按返回值给提示——不要自己判断"这条能不能删"。
- **不缓存**：`api/settings` 的 GET 故意不传 `cacheTtlMs`（`client.request` 默认不缓存），设置页改完必须立刻反映到登记页；写请求本身也会清空 client 的 GET 缓存。
- **失败不回落 mock**：字典是配置数据，加载失败显示错误 + 重试按钮，**不得用兜底值伪装成功**（登记页/数据集页的兜底是另一层：那里兜底的是"接口不可用时保持字典化前的可用性"）。
- `settings` 路由的页头文案在 `src/app/navigation.ts` 的 `workspaceHeaders.settings`；菜单 label 用业务完整称呼「系统设置」。
