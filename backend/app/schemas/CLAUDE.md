# CLAUDE.md — backend/app/schemas/

响应/请求模型与统一信封。当前进度：Task 3（统一信封 + 分页助手）。

## 脚本

- `__init__.py`：空包。
- `common.py`：
  - `ok(data) -> dict`：成功信封 `{"code":0,"message":"ok","data":data}`。
  - `err(code, message, detail=None, status=400) -> JSONResponse`：错误信封 `{"code","message","detail?"}`，`status` 为 HTTP 状态码；`detail` 缺省时不写入 body。
  - `paginate(items, total, page, page_size) -> dict`：分页载荷 `{"items","total","page","page_size"}`。

## 坑/限制

- 错误码约定见 `docs/API接口清单.md`：0=成功；4xxxx=客户端错误（42200 参数校验、40100 未登录、40300 无权限、40400 资源不存在、40900 冲突）；5xxxx=服务端错误（50000）。
- `err()` 返回 `JSONResponse`（**没有 `.json()` 方法**，测试断言用 `json.loads(resp.body)`），不是 dict。
- 新响应模型（Pydantic/SQLModel 子类）后续放本目录各模块；跨域公共结构（信封、分页）统一在此，避免重复定义。
