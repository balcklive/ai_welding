# CLAUDE.md — src/api/

前端接口层（契约：`docs/API接口清单.md`）。当前进度：Task 18（`client.ts` + `types.ts`）已完成；`auth.ts`/`dashboard.ts`/`welds.ts`/`analysis.ts`/`datasets.ts`/`models.ts`/`files.ts`/`jobs.ts`/`reports.ts` 为 Task 19 待填充（占位目录结构见文档 §4.1）。

## 脚本

- `client.ts`：统一请求封装（**原生 fetch，不引 axios**）。
  - `BASE = '/api/v1'`、token 存 `localStorage`（key=`token`）。
  - `getToken() / setToken(token) / clearToken()`：token 读写。
  - `class ApiError extends Error`：`(code, message, status)`——`code` 为信封业务码，`status` 为 HTTP 状态码。
  - `buildQuery(params)`：查询参数 → 查询串（含 `?`）；数组展开为重复键（`channels=a&channels=b`），`undefined/null/''` 跳过。
  - `request<T>(path, options?)`：拼 URL → 注入 `Authorization: Bearer <token>`（有 token 时）→ body JSON 化（有 body 时设 `Content-Type: application/json`）→ 解析信封 → **HTTP 401 → `clearToken()` + `window.location.reload()`**（App 重新挂载回到登录页）→ `code !== 0` 抛 `ApiError` → 返回 `data`。网络失败/非 JSON 响应兜底为 `ApiError(-1, ..., 0)`。
- `types.ts`：全部实体/请求体类型，字段名/形状**逐字对齐后端 `*_payload` 序列化**与 `docs/API接口清单.md` §2、§1.4、§1.5。后端为契约：`Page<T>={items,total,page,page_size}`、`Job<T>={id,type,status,progress,result,error,created_at,finished_at}`、`Registration` = `DataRecord` 别名（`/registrations` 返回同构 record_payload）。

## 坑/限制

- **401 处理是硬约定**：任何业务接口返回 HTTP 401（含登录失败 `POST /auth/login`）都会清 token + 重载页面。这是 Task 18 既定决策（"App 重新挂载即回到登录页"），改它需先确认。
- **查询数组用重复键，不带 `[]` 后缀**：后端 `request.query_params.getlist("channels")` 兼容 `channels=a&channels=b`（也兼容 `channels[]=`），`buildQuery` 已按重复键展开。
- **`unified_vector` 分组**（`types.ts::UnifiedVectorGroup`）：`{name, dims, range:[start,end)}`，42 维分组顺序见 `backend/app/services/features.py` 常量，勿乱改。
- **`Model` 的 `version/metric/status/file_key/latest_version_id` 为可选**：模型无版本时后端不输出这些键（`model_payload` 只在有 `latest` 时并入）。
- **信封错误码约定**：0=成功；4xxxx=客户端错误（40100 未登录、40400 资源不存在、40900 冲突、42200 参数校验）；5xxxx=服务端错误。见 `docs/API接口清单.md` §1.3。
- 新增端点时：请求/响应形状先对齐后端（`backend/app/services` 或 `api/v1/*.py`），再补 `types.ts`；改 `client.ts` 时保持 401/信封解包语义不变。
