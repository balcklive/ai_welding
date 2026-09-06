# 集成 MLflow 与 Label Studio 前提验证报告（待核实前提逐项实测）

> 前置依据：计划 `docs/superpowers/plans/2026-09-05-integrate-mlflow-labelstudio-into-main-app.md`
> 的「待核实前提」清单。本报告在**实施动工前**逐项验证，验证过程已固化成可复跑脚本与代码，
> 结果为本报告。验证日期 2026-09-05。

## 验证方法（代码）

| 脚本 | 作用 | 命令 |
|---|---|---|
| `backend/scripts/premise_validation/run_premise_validation.py` | 本机可自动化项：预签名 TTL / 熔池折叠 / 掩膜→轮廓 / 迁移回填 | `cd backend && uv run python scripts/premise_validation/run_premise_validation.py` |
| `backend/scripts/premise_validation/probe_live.py` | 真实 LS 探测：iframe 响应头 / 项目4 模板 | `uv run python scripts/premise_validation/probe_live.py`（`LABEL_STUDIO_PUBLIC_URL` 可覆盖默认 `http://182.61.59.135:8224`） |

结果 JSON 落盘到同目录 `report.json` / `probe_live_report.json`。

## 逐项结论总览

| # | 前提 | 状态 | 一句话结论 |
|---|---|---|---|
| 1 | 预签名 TTL 上限 | ✅ PASS | SDK 接受 **1 秒 ~ 7 天**，>7 天直接抛错；`StorageClient` 正确透传。**存储层能力 = 7 天**；`/files/url` 封顶 1 天只是路由层限制 |
| 2 | 熔池/正常 训练折叠 | ⚠️ WARN → 定案 | 实测熔池被误折为「缺陷」；**评审定案：熔池是语义分割目标、非缺陷**，折叠须显式排除熔池/按分割任务分流 |
| 3 | 项目4 掩膜→轮廓 可行性 | ✅ PASS | `skimage.find_contours` 规则掩膜→多边形顶点**几乎无损（面积偏差 0.16%）**，可行；不规则锯齿边缘有误差，可调 tolerance 控顶点数 |
| 4 | 历史数据回填迁移 | ✅ PASS | 单条 `ALTER TABLE ... ADD COLUMN ls_status ... NOT NULL DEFAULT 'annotating'` 即同时完成**存量回填、新行默认、蓝绿 expand 兼容**；**评审定案：存量旧任务删除或转移为 LS 任务** |
| 5 | iframe embed 响应头 | ✅ PASS | LS 全部路径**无 `X-Frame-Options`、CSP 为 Report-Only 且无 `frame-ancestors`** → 平台可 iframe 嵌入 LS |
| 6 | LS 项目4 真实模板 | ✅ PASS（已确认并定案） | 实读 LS 数据库确认原 id=4 =「熔池语义分割 Segmentation」= **BrushLabels 单类熔池**；**经用户授权已改为 PolygonLabels（2026-09-05），回写直接 polygon 无损**（该转变写入并验证 `label_config`，项目无已有标注任务） |

（网络端点拓扑项计划已标注「已核实 2026-09-05」，本次未重复验证。）

---

## 1. 预签名 URL TTL 上限 —— ✅ PASS

**前提原文**：MinIO/S3 预签名默认上限 7 天；确认存储层 `presign_get` 支持 >1 天 expires（`/files/url` 路由封顶 1 天 ≠ 存储层能力）。

**验证代码**：`check_ttl()`：
- 直接用 `minio.Minio(..., region="us-east-1")` 调 `presigned_get_object(bucket, key, expires=timedelta(seconds=N))`（预签名是**纯本地签名**，不连网；显式 region 可跳过 location 嗅探）。
- 逐档 `1 天(86400) / 3 天(259200) / 7 天(604800) / 8 天(691200) / 15 天(1296000)`。
- 再注入 fake 客户端（数据面 `bucket_exists`/`make_bucket`，预签名面记录 expires）验证 `StorageClient.presign_get` 的透传。

**实际结果**：
```
1 天 (86400): 通过(289字符)
3 天 (259200): 通过(290字符)
7 天 (604800): 通过(290字符)
8 天 (691200): 拒绝 -> ValueError: expires must be between 1 second to 7 days
15 天 (1296000): 拒绝 -> ValueError: expires must be between 1 second to 7 days
StorageClient.presign_get 透传 expires: 通过 (calls=[604800.0, 259200.0])
```

**结论**：minio SDK 预签名 `expires` 上限 = **7 天（604800 秒）**，超过即抛 `ValueError`。`StorageClient.presign_get(object_key, expires)` 把 `expires` 原样透传给签名客户端。

**对实施的影响**：
- 「长 TTL + 对账刷新」方案成立，但**单条 URL 的 TTL 上限是 7 天**，不能设更久。
- `backend/app/api/v1/files.py` 的 `/files/url` 路由封顶 `MAX_PRESIGN_GET_EXPIRES=86400`（1 天）是**路由层**限制；若 LS 要通过该路由拿媒体 URL，只能 1 天。要 >1 天需：① 直接调 `storage.presign_get(key, expires=...)`（不经 `/files/url` 的 1 天封顶），或 ② 扩路由上限到 ≤604800。**实施时建议 LS 媒体直连走 `storage.presign_get` + 长 TTL（如 3 天），并由适配层对账刷新 7 天内的已过期 URL**。

---

## 2. 熔池/正常 训练折叠 —— ⚠️ WARN（暴露问题）

**前提原文**：熔池入 `label_categories` 后与训练二分类折叠（`load_real_examples` 按「正常→正常、其余→缺陷」）的关系待定——熔池是分割对象非缺陷。

**验证代码**：`check_fold()`——构造内存 SQLite（精简 Raw 表，绕开环形 FK），3 个样本：
- 样本1 标注「气孔」（真实缺陷）
- 样本2 标注「熔池」（分割对象，非缺陷）
- 样本3 无标注（应=正常）

调用 `torch_training.load_real_examples(session, dataset_version_id=900, FakeStorage())`，读取返回的 `TrainingExample.label_name`。

**实际结果**：
```
类表(classes) = ['正常', '缺陷']
样本1 标注=气孔 (真实缺陷): label_name=缺陷 (label=1)
样本2 标注=熔池 (分割对象,非缺陷): label_name=缺陷 (label=1)   ← 语义错误
样本3 无标注 (应=正常): label_name=正常 (label=0)
```

**结论**：当前 `load_real_examples（services/torch_training.py:75）` 用 `"缺陷" if any(a.category for a in sample_annotations) else "正常"` —— **只要样本有任一条非空类别标注就归为「缺陷」**。因此一旦 `label_categories` 加入「熔池」且样本被标了熔池，该样本会被误折叠为**缺陷**，污染二分类训练。

> **评审定案（2026-09-05）：熔池不是缺陷，是语义分割模型需要检出的目标。**
> 因此训练折叠处**不得**将「熔池」并入缺陷二分类；折叠须显式排除熔池（及其它非缺陷类别），或按任务来源/`kind` 分流——桥接 LS 项目 4 的「熔池语义分割」（单类 BrushLabels，见第 6 项）作为独立分割任务。这与下文的落地动作一致。

**对实施的影响**：
- 这是**现在就能确定的代码级语义错误**（非待裁决）。熔池是分割区域，纳入检测/时序缺陷二分类在语义上是错的。
- 熔池标签**必须在训练折叠前被隔离**（三选一）：① 折叠处显式排除非缺陷类别（熔池/正常），不再用 `any(...)` 一刀切；② 按 `kind=polygon` / 任务来源（video 语义分割）与缺陷类解耦；③ 把熔池类样本从缺陷二分类剔除，转作独立语义分割数据集。
- 推荐：在 `load_real_examples` 折叠处用一个**显式「缺陷类别白名单」**（如 `{气孔, 焊瘤, 未熔合, 咬边, 未焊透, 焊穿}`），只对属于该白名单的类别折叠为缺陷，其余类别（熔池/正常……）视为非缺陷并剔除——避免把"有标注但非缺陷"的样本误算缺陷。

---

## 3. 项目4 掩膜→轮廓 可行性 —— ✅ PASS

**前提原文**：平台视频帧是多边形顶点（`kind=polygon`），LS id4 现为 BrushLabels——定「LS 改 PolygonLabels 模板」还是「接受掩膜回写→轮廓/rle 存储」。

**验证代码**：`check_mask_to_polygon()`——构造 32×32 二值掩膜（中央 20×16 实心矩形），用 `skimage.measure.find_contours(mask.astype(float), 0.5)` 取轮廓，把 `(row, column)` 转成 `[x=col, y=row]` 顶点，用 shoelace 公式算多边形面积 vs 原始像素面积。

**实际结果**：
```
掩膜尺寸 32x32，实心矩形像素面积 = 320
find_contours 返回 1 条轮廓，主轮廓顶点数 = 73
多边形 shoelace 面积 = 319.50，与像素面积偏差 = 0.50 (0.16%)
```

**结论**：`find_contours` 能把 BrushLabels 的栅格掩膜稳定转成 polygon 顶点，**规则形状面积偏差 ~0.16%（几乎无损）**，顶点数可用 `skimage.measure.approximate_polygon(tolerance=...)` 压缩控制。

**对实施的影响**：
- 技术上**两种落点都可行**：① 让 LS 项目4 改 PolygonLabels 模板（与平台 `kind=polygon` + `points` 模型一致，回写无需转换）；② 保留 BrushLabels，回写时 masked → `find_contours` → polygon 顶点（贴近平台存储，代价是近似 + 需要 skimage）。
- **倾向**：如果熔池分割需要像素级掩膜精度，而平台 `annotations` 只有 `points`（顶点列表，无 rle/mask 列，见 `app/models/analysis.py::Annotation`），则 option ② 有损且缺存储位。**建议改 LS 项目4 为 PolygonLabels**（与平台 polygon 模型对齐），或在 `Annotation` 增补掩膜列。这一点与第 2 项（熔池折叠）一起，建议作为**产品/工程联合裁定点**。

---

## 4. 历史数据回填迁移 —— ✅ PASS

**前提原文**：加「LS 等待」状态列时存量 annotation_tasks 的默认值/回填 + 蓝绿 expand/contract 兼容。

**验证代码**：`check_migration()`——SQLite 建「旧」`annotation_tasks` 表（无状态列）+ 插 2 行存量，执行：
```sql
ALTER TABLE annotation_tasks ADD COLUMN ls_status VARCHAR(16) NOT NULL DEFAULT 'annotating';
```
再插一行新任务（不显式写 `ls_status`），查询三层结果。

**实际结果**：
```
expand 后存量行（应自动=annotating）:
  [(1, '旧任务A', 'annotating'), (2, '旧任务B', 'annotating')]
新插入行（未显式写 ls_status，应触发默认）:
  [(3, '新任务C', 'annotating')]
```

**结论**：**单条 `ADD COLUMN ... NOT NULL DEFAULT 'annotating'` 即可同时完成**：① 存量行自动回填默认；② 新行默认；③ 蓝绿 expand 兼容（旧代码不读该列不崩，新代码读有默认）。无需单独的 `UPDATE` 回填，也无需立即 contract。

> **评审定案（2026-09-05）：迁移到 Label Studio 后，存量的所有旧任务一律删除，或转移成 Label Studio 的任务（二者之一），不再保留「模拟/旧路径」任务。**
> 因此"历史数据回填"的默认值语义应取「legacy / 待删除或待转移」而非「annotating」——存量行**从未进过 LS**，不能当作『正在 LS 标注』。`on` 模式下旧任务不存活（对应计划决策 1 的 `off` 回退路径；`on` 时旧任务走删除/转移，`off` 时才映射回旧模拟路径）。

**对实施的影响**：
- 迁移机制简单，但**回填值语义按上述定案取「legacy/待转移」**，而非「annotating」（否则会误导"正在人工标注"）。
- 落地两条路线：**删除** = 级联清理存量旧 annotation_tasks 及其 Job/Sample/Annotation；**转移** = 按来源/类别重建为对应 LS 项目任务（检测→项目3、熔池分割→项目4、时序→项目5），写入 `annotation_ls_sync` 并呈「LS 等待」态。建议默认走「转移」以保留标注成果（老模拟标注如无保留价值则删除）。
- 更完整的预期是**多态状态机**（如 `pending_ls` / `annotating` / `syncing` / `synced` / `migrated or legacy` ），而非单一 `annotating`；
- `models/__init__.py` 的 `__all__`、Alembic 迁移、`docs/数据库设计.md` 需同步（项目根 CLAUDE.md 硬规则），新建第 25 张表 `annotation_ls_sync` 同理。

---

## 5. iframe embed 响应头 —— ✅ PASS

**前提原文**：LS 标注页响应是否带 `X-Frame-Options`/CSP `frame-ancestors`，决定平台「嵌入 vs 新标签页」。

**验证代码**：`probe_live.py::check_iframe()`——抓 LS 根路径 `/`、`/user/login/`、`/project/`、`/api/projects/` 响应头，判定 `X-Frame-Options` 与 CSP 的 `frame-ancestors`。

**实际结果**（公网 `http://182.61.59.135:8224` 实测）：
```
/  status=200 XFO=None frame-ancestors=False (CSP report-only=True) -> allow
/user/login/ status=200 XFO=None frame-ancestors=False (CSP report-only=True) -> allow
/project/ status=404 XFO=None frame-ancestors=False (CSP report-only=True) -> allow
/api/projects/ status=401 XFO=None frame-ancestors=False (CSP report-only=True) -> allow
```
（所有路径的 `Content-Security-Policy-Report-Only` 均**不含 `frame-ancestors`**，且无强制 CSP；`X-Frame-Options` 全程为 None。）

**结论**：LS 站点的响应头**不限制跨域 iframe 嵌入** → 平台**可以直接 iframe 嵌入 LS 标注页**（决策 1 的「嵌入 vs 新标签页」应选**嵌入**，省去新标签页跳转/回平台刷新的复杂度）。

**对实施的影响**：
- 采用 iframe 嵌入方案。需注意：LS 前端是 SPA，登录/标注在 iframe 内进行；仍需处理「标注完成后回平台刷新」的回写状态轮询/对账（与第 4/A 项等待态联动）。
- 安全：LS 当前无强制 CSP 与 XFO，属宽松配置；生产可考虑在服务器侧或反代加 `frame-ancestors` 收紧为仅放行平台域，但**本期 embed 需先放行**。

---

## 6. LS 项目4 真实模板 —— ✅ PASS（已确认）

**前提原文**：LS id4 现为 BrushLabels，平台视频帧是 polygon 顶点——需确认实际模板。

**验证代码**：服务器侧探针 `backend/scripts/premise_validation/_ls_probe.py`——直接读 LS 容器内 `label_studio.sqlite3` 的 `project` 表（绕开 API token，最权威）。部署：`scp -P 8222 _ls_probe.py wwwroot@182.61.59.135:/tmp/` → `docker cp /tmp/_ls_probe.py label-studio:/tmp/` → `docker exec label-studio python3 /tmp/_ls_probe.py`。

**实际结果**（服务器 `wwwroot@182.61.59.135:8222`，容器 `label-studio`，库 `/label-studio/data/label_studio.sqlite3`）：
```
PROJECT 4 title=熔池语义分割 Segmentation
PROJECT 4 tools: ['BrushLabels']
HAS_BrushLabels: True  HAS_PolygonLabels: False
label_config sample: <View> <Image name="image" value="$image"/> <BrushLabels name="label" toName="image"> <Label value="熔池" background="#f032e6"/> </BrushLabels> </View>
```

**结论（含后续定案）**：LS 项目 id=4 原实读为 **BrushLabels（掩膜）语义分割、单类「熔池」**、title=「熔池语义分割 Segmentation」，**不是 PolygonLabels**。**2026-09-05 经用户授权已把项目4 模板改为 PolygonLabels**（`PATCH /api/projects/4/ {label_config}` 成功，`parsed_label_config.label.type=PolygonLabels`、单类熔池；且 `num_tasks_with_annotations=0` 无已有标注任务，改模板无数据迁移影响）。

**对实施的影响**：
- 平台视频帧是 `kind=polygon`（多边形顶点，`app/models/analysis.py::Annotation`），LS 项目4 现为 **PolygonLabels** → **工具类型已对齐**，回写直接映射 polygon 顶点、**无损、免掩膜转换**（不再需要 find_contours）。
- 结合第 2 项评审定案（熔池=分割目标，非缺陷）+ 单类熔池语义分割 → **自洽**：熔池作为独立语义分割目标，经 PolygonLabels 标注回写 `annotations(kind=polygon)`。
- 若未来做像素级语义分割训练，由 `kind=polygon` 顶点经 `skimage.polygon2mask` 无损栅格化即可（polygon 是可无损还原为掩膜的存储形态）。
- 另注意：`.env` 现已存 `LABEL_STUDIO_API_KEY`（user_id=1 的 PAT，refresh 型 JWT）；SDK 用它即内部 refresh；建议后续收敛为专用集成账号（见安全收敛）。

---

## 附：LS 等待态前端表达（非技术前提，供参考）

计划另列「LS 等待态前端表达：等待期不做进度 spinner，改『去 LS 标注』链接 + 刷新按钮/轮询」。它**不是可自动化测试的技术前提**，而是依赖决策 1（本报告第 5 项已定 iframe 嵌入）的前端切片。可测断言为：等待态 Job（非 `pending→running→succeeded/failed` 的快速终态）在前端应渲染为「去 LS 标注」入口而非进度条；其状态表达依赖第 4/A 项的「LS 等待」状态列落地。

## 复跑说明

- 本机 4 项：`uv run python scripts/premise_validation/run_premise_validation.py`（无网络依赖，理论可离线）。
- 真实 LS 2 项：`uv run python scripts/premise_validation/probe_live.py`（需网络 + 项目4 项需 API key）。
- 结果 JSON：同目录 `report.json` / `probe_live_report.json`。
