# CLAUDE.md — src/hooks/

前端 React 钩子层（契约：`docs/API接口清单.md` §4.3 横切工具）。当前进度：**Task 20**（`useJob` 通用任务轮询）+ **2026-09-06 一期 LS 感知**（`useLabelStudioTask`）+ **2026-09-14 数据管理改造二期补齐**（`usePagedWelds` 选择器分页、`useIngestStatus` 登记链路状态）。消费 `src/api/` 的域模块，向页面提供轮询/状态封装。

## 脚本

- `useLabelStudioTask.ts`：**2026-09-06 一期·轨道 A**。轮询标注任务的 LS 同步状态（`getLabelStudioTask(taskId)` → `GET /labelstudio/tasks/{job_uid}`）。`useLabelStudioTask(taskId, jobDone)`（`jobDone`=标注 job 是否已终态 succeeded/failed）返回 `{ lsTask, failed }`；`pending_ls`/`annotating` 期间每 3s 轮询；`synced` 停止；**`legacy` 且 `jobDone=false` 继续轮询**（防 executor 运行前的短暂 legacy 窗口错过 LS 态），`legacy` 且 `jobDone=true` 停止（确证 off 路径）。请求失败每 5s 重试并记 `error`。消费方：`features/annotation/AnnotationWorkspace`（仅用 `ls_status` 感知任务是否已被推到 LS，借 `lsActive` 放宽样本加载闸门；**LS 工作台已不再嵌入主应用**，见该目录 CLAUDE.md）。
- `usePagedWelds.ts`：**2026-09-14（T9/R5）**。样本选择器的**服务端搜索 + 分页追加**：`usePagedWelds(datasetId, query, pageSize=20)` → `{ items, total, hasMore, loading, error, loadMore, retry }`。300ms 防抖，默认每页 20（与后端 `page_size` 上限 100 对齐）；**失败时清空候选**（不把上一个数据集/上一个关键词的结果当成这次的结果）；`loadMore` 按 `weld_id` 去重后追加。消费方：`features/data-context/DataContext.tsx` 的 `SelectionSwitcher` 与 `AnalysisSelect`——改造前两处写死 `page_size: 50` 且没有翻页入口，第 51 条之后永远选不到。
- `useIngestStatus.ts`：**2026-09-14（T4.4/R2）**。登记链路状态轮询：`useIngestStatus(registrationId, intervalMs=2000)` → `{ status, error, refresh }`，状态由后端 `GET /registrations/{id}/ingest-status` **从已有数据推导**（刷新/换设备一致）。只在 `importing` 时继续排期（递归 `setTimeout`，终态/失败天然停），避免每 2 秒刷一次错误。另导出 `ingestStatusText(status)` 供页面与数据详情共用文案。
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
