# 数据集层级重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-subagent-driven-development (recommended) or supo-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将数据中心重构为“数据集列表 → 数据集概览 → 数据列表 → 数据详情”，移除独立全局数据列表入口，并让数据列表只读取当前数据集版本的成员。

**Architecture:** 后端新增按数据集版本查询成员的分页接口，沿 `dataset_items → samples → data_records` 查询并返回列表展示所需的焊缝字段与 split。前端在现有 `App.tsx` 中保留大组件结构，但把 `DatasetWorkspace` 的状态从 list/detail 改为 overview/records/record-detail，并通过 selectedDatasetId、selectedDatasetVersionId、selectedDataId维护上下文；数据集概览使用明确 CTA 和卡片入口，不使用横向 Tab。

**Tech Stack:** React 18 + TypeScript + Tailwind/CSS（现有 `src/App.tsx`/`src/index.css`）、FastAPI + SQLModel + pytest + SQLite 测试、uv 管理后端环境。

## Global Constraints

- 前端保持现有 React/Tailwind 视觉语言，不引入新的 UI 库。
- 不重写 `src/App.tsx`，采用最小范围修改并保留现有 mock 兜底。
- 所有 `/api/v1` 调用必须继续经过统一 request 封装并记录访问日志。
- 列表筛选和分页必须服务端执行，前端不得加载全量数据后过滤。
- 数据集版本成员查询必须走 `dataset_items` 固定快照，不直接把全局 `/welds` 当作数据集列表。
- 保留“先选数据，再处理数据”规则；核验、分析、标注仍需 selectedDataId。
- 不新增删除能力；数据集、数据集版本、焊缝的既有生命周期保持不变。
- Python 命令统一使用 `cd backend && uv run ...`；不使用 pip 或系统 Python 安装依赖。
- 修改接口/表/对象键时同步 `docs/API接口清单.md`、`docs/数据库设计.md`、`docs/OSS存储设计.md` 与两端实现；本次不改表结构和对象键，仅更新 API 契约。

---

## 文件结构与职责

### 修改

- `backend/app/services/datasets.py`：增加数据集版本成员查询与列表 payload 组装，负责服务端筛选/分页前的数据查询。
- `backend/app/api/v1/datasets.py`：增加 `GET /datasets/{dataset_id}/versions/{version_id}/items` 路由、参数校验、数据集/版本归属校验和统一响应。
- `backend/app/api/v1/CLAUDE.md`：记录新增成员接口、参数和错误码。
- `backend/app/services/CLAUDE.md`：记录成员查询的数据关系、筛选字段和避免 N+1 的约束。
- `backend/tests/test_datasets.py`：增加成员列表、分页、筛选、跨数据集版本隔离、未登录和错误路径测试。
- `src/api/datasets.ts`：增加成员列表 API 函数。
- `src/api/types.ts`：增加 `DatasetItemRow` 及其分页返回使用的类型。
- `src/App.tsx`：移除独立数据列表导航，调整数据中心默认入口，重构数据集浏览状态和页面入口，增加数据集上下文、成员列表、面包屑和数据详情归属信息。
- `src/App.buffer-regression.test.mjs` 或新增 `src/App.dataset-hierarchy-regression.test.mjs`：增加静态回归断言，防止独立数据列表导航和旧 Tab 主路径回归。
- `src/CLAUDE.md`：同步数据中心路由、状态和 API 接线说明。
- `docs/API接口清单.md`：在 §3.5 增加成员列表接口及响应字段。
- `docs/CLAUDE.md`：记录新增接口契约已回写。

### 不修改

- `backend/app/models/datasets.py`：现有 `DatasetItem` 已包含 `dataset_version_id/sample_id/split`，无需迁移。
- `backend/app/models/analysis.py`、`backend/app/models/data.py`：复用已有 `Sample` 和 `DataRecord`。
- `src/api/welds.ts`：全局焊缝列表接口保留给登记/最近登记等现有功能，不再作为数据集成员列表数据源。

---

## Task 1: 后端数据集版本成员查询

**Files:**
- Modify: `backend/app/services/datasets.py`
- Modify: `backend/app/api/v1/datasets.py`
- Modify: `backend/app/api/v1/CLAUDE.md`
- Modify: `backend/app/services/CLAUDE.md`
- Test: `backend/tests/test_datasets.py`

**Interfaces:**
- Consumes: `DatasetItem`, `Sample`, `DataRecord`, `Dataset`, `DatasetVersion`，以及现有 `paginate()`。
- Produces: `GET /api/v1/datasets/{dataset_id}/versions/{version_id}/items`，返回 `Page[dict]`。

- [ ] **Step 1: 写失败测试，先固定接口行为**

在 `backend/tests/test_datasets.py` 增加以下测试逻辑（沿用文件已有的 TestClient、内存 SQLite、seed 和依赖覆盖 fixtures）：

```python
def test_dataset_version_items_are_scoped_and_filterable(client):
    response = client.get(
        "/api/v1/datasets/1/versions/1/items",
        params={"split": "train", "q": "0248", "page": 1, "page_size": 2},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert set(payload) == {"items", "total", "page", "page_size"}
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert all(item["split"] == "train" for item in payload["items"])
    assert all("weld_id" in item and "registration_no" in item for item in payload["items"])


def test_dataset_version_items_rejects_cross_dataset_version(client):
    response = client.get("/api/v1/datasets/1/versions/999999/items")
    assert response.status_code == 404
    assert response.json()["code"] == 40402


def test_dataset_version_items_requires_auth(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/datasets/1/versions/1/items")
    assert response.status_code == 401
    assert response.json()["code"] == 40100
```

如果 seed 的版本 ID 不是固定值，测试先从 `GET /datasets/1/versions` 读取属于数据集 1 的版本 ID，再使用该 ID；不能依赖数据库自增值的跨测试稳定性。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd backend && uv run pytest tests/test_datasets.py -k "version_items" -v
```

Expected: FAIL，因为成员列表路由尚不存在。

- [ ] **Step 3: 在 service 中实现成员查询**

在 `backend/app/services/datasets.py` 增加明确的函数：

```python
def list_version_items(
    session: Session,
    version: DatasetVersion,
    *,
    q: str | None,
    quality: str | None,
    split: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    ...
```

实现要求：

1. 以 `DatasetItem.dataset_version_id == version.id` 为根条件。
2. 连接 `Sample`，再通过 `Sample` 对应的 `split_task_id`/版本关系解析所属焊缝；若现有 schema 中没有直接 record_id，复用已有 service 的 sample→version→record 解析方式，不增加表字段。
3. 返回字段至少包含 `sample_id`、`weld_id`、`weld_name`、`registration_no`、`source`、`machine`、`modalities`、`quality`、`split`、`frame_no`、`created_at`。
4. `q` 对 `weld_id`、`weld_name`、`registration_no` 做包含匹配；`quality` 精确匹配；`split` 仅允许 `train/val/test`，空值表示不过滤。
5. 先执行 `count`，再按 `sample_id` 稳定排序并使用 `offset/limit`，返回 `(items, total)`。
6. 一次查询完成列表所需的关联字段，禁止在列表循环中逐条调用 `getWeld`。
7. 同一个 `DataRecord` 可能有多个样本，必须按 `dataset_items` 保留样本粒度，不能按 weld_id 去重。

- [ ] **Step 4: 在 API 路由中实现校验和统一分页响应**

在 `backend/app/api/v1/datasets.py` 增加 query 参数：

```python
@router.get("/datasets/{dataset_id}/versions/{version_id}/items")
def list_dataset_version_items(
    dataset_id: str,
    version_id: int,
    q: str | None = None,
    quality: str | None = None,
    split: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict:
    ...
```

路由必须：

- 通过 `get_dataset_by_identifier()` 同时支持 DB id 和 dataset_no。
- 数据集不存在返回 `err(40401, "数据集不存在", status=404)`。
- 版本不存在或不属于该数据集返回 `err(40402, "数据集版本不存在", status=404)`。
- `split` 非 `train/val/test` 时返回 `err(40000, "数据划分参数无效", status=400)`。
- 使用 `paginate(items, total, page, page_size)` 返回统一分页载荷。

- [ ] **Step 5: 运行后端测试确认通过**

Run:

```bash
cd backend && uv run pytest tests/test_datasets.py -k "version_items" -v
```

Expected: PASS。

- [ ] **Step 6: 同步后端目录说明并提交**

在两个 `CLAUDE.md` 中补充接口和查询约束，然后运行：

```bash
git add backend/app/services/datasets.py backend/app/api/v1/datasets.py \
  backend/app/api/v1/CLAUDE.md backend/app/services/CLAUDE.md backend/tests/test_datasets.py
git commit -m "feat: add dataset version member listing"
```

---

## Task 2: 前端 API 类型和契约接线

**Files:**
- Modify: `src/api/types.ts`
- Modify: `src/api/datasets.ts`
- Modify: `docs/API接口清单.md`
- Modify: `docs/CLAUDE.md`
- Test: `src/App.dataset-hierarchy-regression.test.mjs`

**Interfaces:**
- Consumes: Task 1 的成员列表接口。
- Produces: `listDatasetVersionItems(datasetId, versionId, params): Promise<Page<DatasetItemRow>>`。

- [ ] **Step 1: 写失败静态契约测试**

新增 `src/App.dataset-hierarchy-regression.test.mjs`，先写以下断言：

```js
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const datasetsApi = fs.readFileSync(new URL('./api/datasets.ts', import.meta.url), 'utf8');

assert.match(datasetsApi, /listDatasetVersionItems/);
assert.match(datasetsApi, /\/datasets\/\$\{datasetId\}\/versions\/\$\{versionId\}\/items/);
assert.doesNotMatch(app, /\{ route: 'data-center\/list', label: '数据列表' \}/);
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
node src/App.dataset-hierarchy-regression.test.mjs
```

Expected: FAIL，因为类型/API 函数和导航调整尚未实现。

- [ ] **Step 3: 增加前端类型和 API 函数**

在 `src/api/types.ts` 增加：

```ts
export interface DatasetItemRow {
  sample_id: number;
  weld_id: string | null;
  weld_name: string | null;
  registration_no: string | null;
  source: string | null;
  machine: string | null;
  modalities: string[];
  quality: string | null;
  split: 'train' | 'val' | 'test';
  frame_no: number | null;
  created_at: string | null;
}
```

在 `src/api/datasets.ts` 增加：

```ts
export interface DatasetItemQuery {
  q?: string;
  quality?: string;
  split?: 'train' | 'val' | 'test';
  page?: number;
  page_size?: number;
}

export async function listDatasetVersionItems(
  datasetId: string,
  versionId: number,
  params: DatasetItemQuery = {},
): Promise<Page<DatasetItemRow>> {
  return request<Page<DatasetItemRow>>(
    `/datasets/${datasetId}/versions/${versionId}/items`,
    { query: params },
  );
}
```

同时导入 `Page` 和 `DatasetItemRow` 类型。函数参数必须使用 `datasetId`/`versionId`，不要把成员查询复用成 `listWelds`。

- [ ] **Step 4: 更新接口契约文档**

在 `docs/API接口清单.md` §3.5 的版本接口之后增加成员列表接口，明确：

```text
GET /api/v1/datasets/{dataset_id}/versions/{version_id}/items
query: q, quality, split(train|val|test), page, page_size
response: Page<DatasetItemRow>
```

说明该接口以 `dataset_items` 为固定快照来源，按样本粒度返回，不使用全局 `/welds` 前端过滤。

- [ ] **Step 5: 运行静态测试**

Run:

```bash
node src/App.dataset-hierarchy-regression.test.mjs
```

Expected: 仍可能因 App 导航断言失败；API 类型和函数断言应先通过，下一任务完成导航后整体通过。

- [ ] **Step 6: 提交 API 契约变更**

```bash
git add src/api/types.ts src/api/datasets.ts docs/API接口清单.md docs/CLAUDE.md \
  src/App.dataset-hierarchy-regression.test.mjs
git commit -m "feat: expose dataset version item api"
```

---

## Task 3: 前端数据中心层级和页面交互

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/index.css`（仅补充新页面所需样式）
- Modify: `src/CLAUDE.md`
- Test: `src/App.dataset-hierarchy-regression.test.mjs`

**Interfaces:**
- Consumes: `listDatasets`, `getDataset`, `getDimensions`, `getReadiness`, `listDatasetVersions`, `getLineage`, `listDatasetVersionItems`。
- Produces: `DatasetWorkspace` 的三个可验证状态：`overview`、`records`、`record-detail`，以及 dataset/data context 传递给现有下游流程。

- [ ] **Step 1: 固定前端层级回归测试要求**

将静态测试扩展为以下断言：

```js
assert.match(app, /label: '数据集'/);
assert.doesNotMatch(app, /route: 'data-center\/list'/);
assert.match(app, /查看当前版本数据/);
assert.match(app, /数据集概览/);
assert.match(app, /listDatasetVersionItems/);
assert.match(app, /所属数据集/);
assert.doesNotMatch(app, /dataset-subtabs/);
```

- [ ] **Step 2: 调整路由和导航入口**

修改 `Route` 与 `navStructure`：

- 移除 `data-center/list` 路由和“数据列表”子项。
- 保留 `data-center/datasets` 作为数据中心浏览入口。
- 数据中心组按钮点击时执行 `navigate('data-center/datasets')` 并展开子菜单，而不是只展开不进入页面。
- `WorkspaceFrame` 继续把 `data-center/datasets` 渲染为 `DatasetWorkspace`。
- `DatasetWorkspace` 初始状态为 `overview`，首次进入默认选择 API 返回的第一个数据集，但不自动进入数据列表。

现有需要具体数据的 `routesRequiringData` 继续依赖 `selectedDataId`；数据登记仍不加入该数组，保证登记是新建操作。

- [ ] **Step 3: 重构 DatasetWorkspace 状态**

将当前 `view: 'list' | 'detail'` 改成：

```ts
type DatasetView = 'overview' | 'records' | 'record-detail';
const [view, setView] = useState<DatasetView>('overview');
const [selectedId, setSelectedId] = useState<string | null>(null);
const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
```

行为要求：

1. API 数据集列表加载成功后，若尚无 `selectedId`，选中第一条数据集，并把其 `current_version_id` 作为 `selectedVersionId`。
2. 点击数据集列表行进入 `overview`，不进入旧的内嵌 detail Tab。
3. 概览主 CTA 文案为 `查看当前版本数据 · {count} 条`；有当前版本时进入 `records`，无当前版本时文案为 `创建数据集版本` 并调用已有创建版本流程。
4. 版本卡点击进入版本列表/版本管理视图；该视图可以沿用现有 `DatasetDetail` 的版本区域，但不能使用 `dataset-subtabs` 作为主导航。
5. 质量和血缘使用概览中的摘要卡/按钮打开或定位到同页对应区块，不新增横向 Tab。
6. 版本切换时更新 `selectedVersionId`，清空 `selectedRecordId` 和 `selectedDataId`，重新拉取成员列表。

- [ ] **Step 4: 实现 DatasetRecords 成员列表**

在 `src/App.tsx` 中新增同文件组件 `DatasetRecords`，props 明确为：

```ts
{
  dataset: DatasetRow;
  versionId: number;
  onBack: () => void;
  onVersionChange: (versionId: number) => void;
  onSelectRecord: (row: DatasetItemRow) => void;
}
```

组件实现：

- 维护 `query`、`quality`、`split`、`page`、`rows`、`total`。
- 在 `useEffect` 中调用 `listDatasetVersionItems(String(dataset.id), versionId, { q, quality, split, page, page_size: PAGE_SIZE })`。
- 搜索、质量、划分变化时把 page 重置为 1；仅依赖这些值和 `versionId` 发请求。
- 请求失败时保留 mock 成员行，并显示非阻塞状态提示，不渲染空白页面。
- 页面顶部显示面包屑和上下文卡：数据集名称、当前版本、样本数、训练/验证/测试统计、返回概览、切换版本。
- 列表按样本粒度显示：样本/焊缝 ID、登记编号、来源、焊机、模态、核验状态、数据划分、采集时间。
- 点击行设置 selectedRecordId/selectedDataId，并切换到 `record-detail`。
- “训练集/验证集/测试集”使用中文展示，传给 API 的值保持 `train/val/test`。
- 分页显示 `page / totalPages`，按钮在边界禁用。

- [ ] **Step 5: 复用现有数据详情能力，增加归属上下文**

如果当前 App 中没有独立数据详情组件，则从现有 `ManagementFiltered` 的行字段和 `getWeld` 使用逻辑中抽取最小 `DatasetRecordDetail` 组件，不重写核验/分析页面。组件必须接收：

```ts
{
  weldId: string;
  dataset: DatasetRow;
  versionId: number;
  split: 'train' | 'val' | 'test';
  onBack: () => void;
  setSelectedDataId: (id: string) => void;
  navigate: (route: Route) => void;
}
```

页面顶部显示：

```text
数据中心 / 数据集列表 / {dataset.name} / 当前版本数据 / {weldId}
```

详情信息中明确显示：所属数据集、所属版本、数据划分；现有数据核验、数据版本和分析入口继续通过 `selectedDataId` 进入，不改变 API。

- [ ] **Step 6: 添加概览卡片和面包屑样式**

只在 `src/index.css` 增加带已有命名风格的类：

- `.dataset-breadcrumb`
- `.dataset-context-card`
- `.dataset-primary-entry`
- `.dataset-summary-links`
- `.dataset-records-header`
- `.dataset-records-table`
- `.dataset-empty-state`

样式要求：主 CTA 为页面唯一高强调操作；辅助入口使用现有 `outline-button`/`ghost-button`；面包屑和上下文卡在移动宽度下换行；删除或停止使用 `.dataset-subtabs`。

- [ ] **Step 7: 更新数据中心文档说明并运行前端测试**

更新 `src/CLAUDE.md` 的路由与数据中心接线说明，运行：

```bash
node src/App.dataset-hierarchy-regression.test.mjs
npm run build
```

Expected: 静态回归测试 PASS，生产构建 PASS。

- [ ] **Step 8: 提交前端层级重构**

```bash
git add src/App.tsx src/index.css src/CLAUDE.md src/App.dataset-hierarchy-regression.test.mjs
 git commit -m "feat: reorganize dataset browsing hierarchy"
```

---

## Task 4: 全量验证、文档一致性和视觉验收

**Files:**
- Modify: `docs/API接口清单.md`（仅在验证中发现契约描述遗漏时修正）
- Modify: `docs/CLAUDE.md`
- Modify: `src/CLAUDE.md`
- Modify: `backend/app/api/v1/CLAUDE.md`
- Modify: `backend/app/services/CLAUDE.md`

**Interfaces:**
- Consumes: Tasks 1–3 的后端接口、前端页面和回归测试。
- Produces: 可验收的四层数据浏览流程，无独立全局数据列表入口。

- [ ] **Step 1: 运行后端全量测试**

```bash
cd backend && uv run pytest
```

Expected: 所有既有测试和新增数据集成员测试 PASS。

- [ ] **Step 2: 运行前端全量测试和构建**

```bash
node src/App.buffer-regression.test.mjs
node src/App.overview-regression.test.mjs
node src/App.toolbar-regression.test.mjs
node src/vite-base-regression.test.mjs
node src/App.dataset-hierarchy-regression.test.mjs
npm run build
```

Expected: 全部 Node 回归测试 PASS，Vite 构建 PASS。

- [ ] **Step 3: 进行浏览器验收**

启动前端和后端后，按以下路径验收：

1. 点击“数据中心”，直接进入数据集列表。
2. 确认侧边栏没有独立“数据列表”。
3. 点击一个数据集，进入数据集概览。
4. 确认主 CTA 显示“查看当前版本数据 · N 条”。
5. 点击 CTA，确认数据列表只显示当前数据集版本成员。
6. 使用关键词、质量、数据划分筛选，确认请求 query 改变且结果由服务端返回。
7. 点击一行进入数据详情，确认面包屑和所属数据集/版本/划分可见。
8. 点击返回，确认回到当前数据集版本列表而非全局列表。
9. 切换版本，确认数据列表、统计、面包屑和选中数据同步更新。
10. 从数据详情进入核验/分析，确认既有“先选数据”流程仍正常。
11. 检查无当前版本、无成员、API 失败状态均有文字说明。

- [ ] **Step 4: 做一次契约/代码自检**

运行：

```bash
git diff --check
rg -n "data-center/list|dataset-subtabs|listWelds\(" src/App.tsx
rg -n "dataset_version.*items|list_version_items" backend/app docs/API接口清单.md
```

Expected：

- `src/App.tsx` 不再包含独立 `data-center/list` 和用于主层级的 `dataset-subtabs`。
- `DatasetRecords` 不调用 `listWelds`。
- 后端路由、service、前端 API、契约文档都包含同一个 `/datasets/{dataset_id}/versions/{version_id}/items` 接口。

- [ ] **Step 5: 更新目录状态说明并提交**

将验收结果和新增接口记录到相关 `CLAUDE.md`，然后运行：

```bash
git add docs/CLAUDE.md src/CLAUDE.md backend/app/api/v1/CLAUDE.md backend/app/services/CLAUDE.md docs/API接口清单.md
git commit -m "docs: record dataset hierarchy implementation"
```

---

## 预期效果

### 用户体验

- 用户进入数据中心后，第一认知对象是“数据集”，不会再面对孤立的全局数据列表。
- 每条数据都带有明确上下文：所属数据集、所属版本、训练/验证/测试划分。
- 数据集概览成为清晰的决策页，用户通过“查看当前版本数据”自然进入下一层。
- 版本、质量、血缘成为数据集资产信息，不再与数据列表争夺 Tab 空间。
- 返回、刷新、版本切换时路径和上下文稳定。

### 业务一致性

- 前端层级与后端 `datasets → dataset_versions → dataset_items → samples/data_records` 一致。
- 数据集列表不会误展示数据集之外的焊缝数据。
- 固定版本的成员清单与训练/测试可复现要求保持一致。
- 既有数据核验、版本、分析、标注能力不受破坏。

### 技术效果

- 成员查询服务端分页和筛选，避免全量加载与前端过滤。
- 查询一次返回列表所需字段，避免逐行 N+1 请求。
- 沿用现有 API 信封、鉴权、日志、mock 兜底与测试体系。
- 不改表结构和对象存储，不引入额外依赖。

## 计划自检

- 设计文档第 3 节的层级、交互和面包屑由 Task 3 覆盖。
- 设计文档第 5 节的最小侵入前端边界由 Task 2/3 覆盖。
- 设计文档第 6 节的成员查询接口和分页/筛选由 Task 1/2 覆盖。
- 设计文档第 7 节的空状态与版本切换由 Task 3 覆盖。
- 设计文档第 8 节的验收标准由 Task 4 覆盖。
- 已扫描计划内容，无 `TODO`、`TBD` 或未定义接口名称。
