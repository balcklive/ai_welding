# CLAUDE.md — backend/app/api/

API 路由层。Task 3 建立 v1 聚合骨架，各域模块为占位（后续任务逐个填充实现）；Task 7 填充 `v1/jobs.py`、Task 8 填充 `v1/dashboard.py`（详见 `v1/CLAUDE.md`）。

## 脚本

- `__init__.py`：空包。
- `deps.py`：**Task 5**。`get_current_user(session=Depends(get_session), authorization: str | None = Header(None)) -> User`——解析 `Authorization: Bearer <token>` → `security.decode_token` 得 user id → `session.get(User, id)` 返回 `User`；缺头/非 Bearer/token 无效/用户不存在一律 `HTTPException(401, "未登录或令牌失效")`（由 `main.py` 全局处理器兜底为 `err(40100, ...)`）。
- `v1/`：v1 版本路由聚合（`/api/v1` 前缀在 `main.py` 挂载时统一加），详见 `v1/CLAUDE.md`。

## 坑/限制

- 各域 router 自身**不带前缀**；`/api/v1` 前缀由 `main.py` 的 `include_router(api_router, prefix="/api/v1")` 统一添加，不要再在域模块里加前缀。
