# CLAUDE.md — backend/app/schemas/

响应/请求模型与统一信封。当前进度：Task 3（统一信封 + 分页助手）。

## 脚本

- `__init__.py`：空包。
- `common.py`：
  - `ok(data) -> dict`：成功信封 `{"code":0,"message":"ok","data":data}`。
  - `err(code, message, detail=None, status=400) -> JSONResponse`：错误信封 `{"code","message","detail?"}`，`status` 为 HTTP 状态码；`detail` 缺省时不写入 body。
  - `paginate(items, total, page, page_size) -> dict`：分页载荷 `{"items","total","page","page_size"}`。

## 坑/限制

- 错误码约定见 `docs/API接口清单.md`：0=成功；4xxxx=客户端错误；5xxxx=服务端错误。**实际使用（以代码为准）**：
  - `40000` 参数错误（显式 `err(...)`，各域最常用）
  - `40100` 未登录/令牌失效（`deps.get_current_user` 抛 HTTPException 401 → 全局映射）
  - `40300` 无权限（HTTPException 403 映射，本期未细分角色）
  - `40400` 资源不存在（HTTPException 404 兜底）
  - `40401` **焊缝/登记/版本/任务/数据集/模型等业务实体不存在**（各域显式，如 `jobs.py` 的"任务不存在"）
  - `40402` 版本不存在 / 版本不属于该数据集（`welds`/`datasets`）
  - `40403` 该版本尚未核验（`welds`）
  - `40900` 冲突（同名数据集/模型）
  - `42200` 参数校验失败（`RequestValidationError` 全局映射）
  - `50000` 服务内部错误（HTTPException 其他状态码 / 兜底 `Exception` 全局映射）
- `err()` 返回 `JSONResponse`（**没有 `.json()` 方法**，测试断言用 `json.loads(resp.body)`），不是 dict。
- 新响应模型（Pydantic/SQLModel 子类）后续放本目录各模块；跨域公共结构（信封、分页）统一在此，避免重复定义。
