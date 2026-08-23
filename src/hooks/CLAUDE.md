# CLAUDE.md — src/hooks/

前端 React 钩子层（契约：`docs/API接口清单.md` §4.3 横切工具）。当前进度：**Task 20**（`useJob` 通用任务轮询）。消费 `src/api/` 的域模块，向页面提供轮询/状态封装。

## 脚本

- `useJob.ts`：通用异步任务轮询钩子。
  - `useJob<T = unknown>(jobId: string | null, intervalMs = 1500)` → `{ job, status, progress, result, error, start, stop }`。
    - `job: Job<T> | null`——最近一次轮询到的 Job；从未拉取/已停止后为 `null`。
    - `status: Job<T>['status'] | null`、`progress: number`、`result: T | null`——均由 `job` 派生（`result` 仅 `succeeded` 后才有值）。
    - `error: unknown`——最近一次请求失败（网络 / 非 0 信封码，均为 `ApiError`）；成功轮询时清空。
    - `start()` / `stop()`——手动开始/停止轮询（幂等；`jobId` 为 null 时 `start` 为空操作，`stop` 保留当前 job 不重置）。
  - 行为：
    - `jobId` 非空 → 自动开始：**立即首拉 + `setInterval(intervalMs)`**，直到 `succeeded` / `failed` 自动停。
    - `jobId` 为 `null` → 停止并清空 `job`/`error`。
    - `jobId` 变化 → 自动重新开始；在途旧响应会被丢弃（`jobIdRef.current !== current` 守卫），防串任务。
    - 卸载 → 清定时器 + `mountedRef=false`，`setState` 前检查，杜绝卸载后 setState。
  - 实现要点：
    - `jobId` / `intervalMs` 存 ref，interval 回调每次读到最新值，**不因参数变化重建定时器**；effect 仅依赖 `jobId`。
    - `getJob` 返回 `Job<unknown>`，赋给 `Job<T>` 无需显式 `as`（`unknown` 可赋给任意 `T`）。
    - 失败（`failed` 或请求出错）不自动停止轮询：`failed` 状态本身来自成功响应会停；网络瞬时错误只记 `error`，等下一个 interval 重试（除非调用方 `stop`）。

## 坑 / 限制

- 返回的是新对象，调用方若把它放进 `useEffect` 依赖会每帧触发；请解构取具体字段（`const { status, progress } = useJob(...)`）。
- 本目录是新目录，脚本新增时同步更新本文件。
