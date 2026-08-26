# 功能验证测试与修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-subagent-driven-development (recommended) or supo-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/功能验证测试清单.md` 在试验数据库和 MinIO 上完成 P0、P1、P2 功能验证，并对可复现问题执行修复、验证和独立审查闭环。

**Architecture:** 主 agent 只负责阶段编排、ledger 和结果汇总。每个阶段由独立测试 subagent 产生证据报告；若有失败，由独立修复 subagent 修改代码并补测试，再由独立验证 subagent 复测，最后由独立审查 subagent 审查 diff 和证据。阶段之间串行，避免测试数据和代码修改互相污染。

**Tech Stack:** FastAPI + pytest + SQLModel + MySQL + MinIO；React 18 + TypeScript + Vite；uv；Playwright/HTTP 客户端；loguru API 日志。

## Global Constraints

- 测试账号只从当前本地 `.env` 或运行环境读取，禁止把密码、token 或完整敏感响应写入代码、文档、报告或 git 历史。
- Python 环境一律用 uv 管理：`cd backend && uv run pytest`；禁止 `pip install`、`python -m venv`、直接跑系统 python 装包。
- 所有 `/api/v1` 调用必须记录请求体、返回体、调用人、调用时间等，并按现有 loguru 轮转日志规范脱敏。
- P2 允许在当前试验数据库和 MinIO 桶执行，但必须使用 `backend/tests/fixtures/destructive/` 并记录新增数据、Job、对象和日志证据。
- 预期 4xx 必须确认不是 500；修复不得破坏现有模拟实现边界和“先选数据，再处理数据”规则。
- 主 agent 不直接修改业务代码；所有修复由修复 subagent 完成并经过验证 subagent 与审查 subagent。

---

### Task 1: 基线与测试设施确认

**Files:**
- Read: `docs/功能验证测试清单.md`
- Read: `docs/破坏性测试指导.md`
- Read: `backend/tests/fixtures/destructive/MANIFEST.md`
- Create: `.superpowers/sdd/2026-08-25-feature-validation-subagent-plan/progress.md`
- Create: `.superpowers/sdd/2026-08-25-feature-validation-subagent-plan/task-1-baseline-report.md`

**Interfaces:**
- Consumes: 根目录 `.env` 的服务配置；后端 `:8000`；前端 `:5173`。
- Produces: 基线命令结果、服务可用性、fixture 清单和测试记录格式，供后续各阶段使用。

- [ ] **Step 1: 检查服务和环境**

  测试 subagent 执行 `GET /api/v1/health`、登录、MySQL/MinIO 连通性检查，并确认前端开发服务地址；报告只能记录状态码、脱敏后的标识和 object key 前缀。

- [ ] **Step 2: 执行现有自动化基线**

  运行：

  ```bash
  cd backend && uv run pytest
  npm run lint
  npm run typecheck
  npm run build
  ```

  记录每个命令的退出码和失败测试，不在此阶段修改代码。

- [ ] **Step 3: 建立测试记录与 ledger**

  创建阶段报告和 progress ledger；每项记录编号、时间、subagent、实体/版本/Job、请求或页面结果、日志/对象证据、预期、实际和状态。

- [ ] **Step 4: 基线审查**

  独立审查 subagent 检查基线报告是否遗漏服务依赖、敏感信息、失败命令和可复现步骤；若有设施问题，先解决后进入 Task 2。

---

### Task 2: P0 业务链路验证

**Files:**
- Read: `backend/app/`、`src/` 中版本、对齐、切分和标注实现
- Create: `.superpowers/sdd/2026-08-25-feature-validation-subagent-plan/task-2-p0-report.md`
- Modify: 仅当修复 subagent 根据失败报告确认存在缺陷时修改相应业务文件和测试文件

**Interfaces:**
- Consumes: Task 1 的服务基线和测试记录格式。
- Produces: `VER-*`、`ALIGN-*`、`SPLIT-*`、`LABEL-*` 用例状态以及对应 API、Job、数据库和 MinIO 证据。

- [ ] **Step 1: 测试版本管理**

  测试 subagent 执行 VER-001 至 VER-007，覆盖版本链、去噪、人工修正、对齐生成版本、最新版本列表、历史版本隔离和非法/重复参数；记录 4xx 与 500 情况。

- [ ] **Step 2: 测试对齐和切分**

  执行 ALIGN-001 至 ALIGN-008 与 SPLIT-001 至 SPLIT-009；轮询 Job 的等待、运行、成功、失败状态，核对请求参数、版本、样本来源、MinIO `processed/{weld_id}/` 产物和重复提交行为。

- [ ] **Step 3: 测试标注**

  执行 LABEL-001 至 LABEL-010；分别验证真实 MinIO 图片存在和不存在，检查框编辑、标签切换、AI 预标注、人工保存、刷新持久化、空/重叠/越界输入、重复保存和静态回退。

- [ ] **Step 4: 修复 P0 失败项**

  修复 subagent 读取测试报告，先为每个可修复失败补充最小回归测试，再修改业务代码；运行覆盖测试并提交独立 commit。纯算法模拟边界不得被误改为算法精度承诺。

- [ ] **Step 5: 独立验证与审查**

  验证 subagent 复测所有失败用例及相关成功用例；审查 subagent 检查 diff、事务/幂等、数据版本隔离、异常提示、敏感日志和测试证据。未解决的 Critical/Important 问题回到 Step 4，最多五轮。

---

### Task 3: P1 分析、特征、数据集与模型验证

**Files:**
- Read: `backend/app/api/`、`backend/app/services/`、`src/api/`、`src/App.tsx`
- Create: `.superpowers/sdd/2026-08-25-feature-validation-subagent-plan/task-3-p1-model-report.md`
- Modify: 仅由修复 subagent 修改被报告明确覆盖的后端、前端和测试文件

**Interfaces:**
- Consumes: Task 2 的有效焊缝、版本、Job 和样本。
- Produces: `SIG-*`、`FEAT-*`、`DATASET-*`、`MODEL-*`、`TRAIN-*`、`TEST-*`、`INFER-*` 状态及任务、版本、权重、样本血缘证据。

- [ ] **Step 1: 测试高级信号和特征**

  执行 SIG-001 至 SIG-008 与 FEAT-001 至 FEAT-006；验证六种分析模式、通道/滤波联动、非法参数、真实/生成来源、抽稀上限、三类特征、归一化、维度、重复提取和缺失模态。

- [ ] **Step 2: 测试数据集和血缘**

  执行 DATASET-001 至 DATASET-010；验证四类数据集、详情统计、焊缝分组防泄漏、固定版本、旧版本复现、血缘、必需/可选模态和禁止训练条件。

- [ ] **Step 3: 测试模型、训练、测试和推理**

  执行 MODEL-001 至 MODEL-006、TRAIN-001 至 TRAIN-008、TEST-001 至 TEST-005、INFER-001 至 INFER-006；验证冲突、状态、Job 轮询、刷新恢复、权重 `models/{model_version_id}/weights.pt`、测试指标、文件格式/损坏文件和 `uploads/` 生命周期。

- [ ] **Step 4: 修复、验证、审查**

  修复 subagent 只处理本任务失败项并补回归测试；验证 subagent 执行失败项和跨模块回归；审查 subagent 检查版本关联、Job 幂等、对象键、前端 loading/error 状态和模拟边界。Critical/Important findings 按最多五轮闭环。

---

### Task 4: P1 报告、存储、审计、鉴权与前端稳定性

**Files:**
- Read: `docs/API接口清单.md`、`docs/OSS存储设计.md`、`backend/app/core/logging.py`、`src/api/client.ts`
- Create: `.superpowers/sdd/2026-08-25-feature-validation-subagent-plan/task-4-p1-platform-report.md`
- Modify: 仅由修复 subagent 修改被报告覆盖的文件和回归测试

**Interfaces:**
- Consumes: 前面阶段产生的焊缝、版本、数据集、模型、报告和对象。
- Produces: `REPORT-*`、`OSS-*`、`AUDIT-*`、`AUTH-*`、`UI-*` 状态以及报告 URL、日志和页面证据。

- [ ] **Step 1: 测试报告和对象存储**

  执行 REPORT-001 至 REPORT-010 与 OSS-001 至 OSS-009；核对 PDF/JSON 内容、当前实体引用、真实信号来源、对象前缀、预签名过期、路径穿越、PUT 失败持久化和重复挂载。

- [ ] **Step 2: 测试审计和鉴权**

  执行 AUDIT-001 至 AUDIT-007 与 AUTH-001 至 AUTH-007；核对登录成功/失败、资源访问、越权、非法 ID、401 信封、速率限制观察和敏感字段脱敏。

- [ ] **Step 3: 测试前端容错**

  执行 UI-001 至 UI-008；在后端停止、401/404/409/422/500、网络中断、Job 长轮询、快速路由切换、空数据、超长中文名和窄屏下检查无白屏、无永久 loading、无重复提交和布局可用性。

- [ ] **Step 4: 修复、验证、审查**

  修复 subagent 为每个可修复问题增加对应测试或 Playwright/API 复现；验证 subagent 在服务运行和故障状态分别复测；审查 subagent 检查权限边界、日志脱敏、对象生命周期、错误信封和前端竞态。

---

### Task 5: P2 边界、并发、负载和故障恢复

**Files:**
- Read: `docs/破坏性测试指导.md`、`backend/tests/fixtures/destructive/`
- Create: `.superpowers/sdd/2026-08-25-feature-validation-subagent-plan/task-5-p2-report.md`
- Modify: 仅由修复 subagent 修改确认存在问题的业务文件、测试文件或受控测试脚本

**Interfaces:**
- Consumes: 试验数据库、MinIO `aiwelding` 桶、destructive fixtures、Task 1 的服务基线。
- Produces: `BOUNDARY-*`、`LOAD-*` 状态、并发响应统计、数据/对象增量、日志证据和恢复结果。

- [ ] **Step 1: 执行输入边界与注入测试**

  执行 BOUNDARY-001 至 BOUNDARY-009；覆盖 SQL/XSS 字符串、分页边界、非法分析参数、0 字节、CSV 编码/坏行/超量程、损坏媒体、伪扩展名、超大文件和路径穿越，确认无 500、无白屏、无路径泄露。

- [ ] **Step 2: 执行受控并发与负载测试**

  执行 LOAD-001 至 LOAD-006；使用清单规定的并发规模，记录成功率、4xx/5xx、延迟、连接池、Job 行数、对象数量和重复数据；登录暴力测试只使用受控字典和试验账号。

- [ ] **Step 3: 执行恢复验证**

  在测试 agent 报告新增数据、对象和日志范围后，验证 agent 检查服务重启、任务刷新恢复、失败任务终态和测试数据清理/可追溯性。

- [ ] **Step 4: 修复、验证、审查**

  修复 subagent 处理确认的安全、稳定性和幂等问题；验证 subagent 重放原始边界/并发用例和关键回归；审查 subagent 重点检查 DoS、竞态、事务、资源泄漏和日志敏感信息。

---

### Task 6: 最终回归与验收报告

**Files:**
- Read: 全部前述测试报告、修复报告、验证报告和审查报告
- Create: `.superpowers/sdd/2026-08-25-feature-validation-subagent-plan/final-validation-report.md`
- Modify: `docs/功能验证测试清单.md` 仅在由最终报告确认状态和证据后更新勾选/备注

**Interfaces:**
- Consumes: Task 1–5 的报告、ledger、git commits、数据库/MinIO/日志证据。
- Produces: 完整清单状态、修复列表、遗留风险、模拟边界说明和最终审查结论。

- [ ] **Step 1: 执行最终自动化回归**

  运行 `cd backend && uv run pytest`、`npm run lint`、`npm run typecheck`、`npm run build`，并复测所有曾失败的编号。

- [ ] **Step 2: 独立最终验证**

  验证 subagent 对照清单逐项检查是否都有状态和证据，确认修复未造成版本、Job、文件、报告、权限和前端回归。

- [ ] **Step 3: 独立全分支审查**

  最终审查 subagent 检查所有修复 diff、测试新增、数据边界、日志脱敏、文档一致性和遗留风险；Critical/Important finding 由一个修复 subagent 统一处理，再做一次范围审查。

- [ ] **Step 4: 生成验收报告**

  汇总通过、失败、阻塞、不适用、已修复和遗留项；每个遗留项包含编号、严重级别、影响、复现步骤、证据和处理建议；明确当前模拟算法不属于精度验收。

- [ ] **Step 5: 提交文档与代码变更**

  由主 agent 仅提交已审查的测试记录、验收报告和 subagent 产生的代码/测试 commit；提交前确认 git 状态、无敏感信息、工作区和测试结果一致。
