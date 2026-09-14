/**
 * src/shared/lib/errors.ts — 请求错误 → 用户可读文案（T3.1）
 *
 * 不直接透传后端 message：按 HTTP 状态码/错误类型翻译成用户语言；字段级校验错误
 * （FastAPI 422 + `detail.errors()`，含 `loc` 字段路径）映射成「字段中文名：原因」，
 * 让用户知道到底哪个输入不对，而不是笼统的"失败，请重试"。
 *
 * 刻意**不 import** `api/client` 的 `ApiError`：本文件属纯工具层，只做结构化判断
 * （鸭子类型：只要带 `code`/`status` 就当 ApiError 处理）。这也让本文件零依赖，
 * 可被 `node --test` 直接 import 做单测（见 `src/errors.test.mjs`）。
 */

export interface UserError {
  /** 主文案：一句话，含场景名。 */
  message: string;
  /** 可展示的原因明细（字段级错误 / 业务冲突原因）；没有则为 undefined。 */
  reason?: string;
}

/**
 * 后端字段名 → 界面中文名（Pydantic `loc` 的最后一段）。
 * 未知字段回退为原字段名，不隐藏信息。
 */
const FIELD_LABELS: Record<string, string> = {
  dataset_id: '所属数据集',
  source: '数据来源',
  collected_at: '采集时间',
  weld_name: '样本名称',
  product: '关联产品信息',
  machine: '焊机型号',
  weld_method: '焊接方法',
  material: '板材材质',
  thickness: '板材厚度',
  current_a: '电流',
  voltage_v: '电压',
  current_voltage: '电流/电压',
  sample_rate: '采样频率',
  wire_feed_speed: '送丝速度',
  welding_speed: '焊接速度',
  weld_id: '样本标识',
  registration_no: '登记编号',
  version_id: '数据版本',
  object_keys: '文件',
  labels: '标注',
  name: '名称',
  task: '任务类型',
  format: '格式',
  normalization: '归一化方式',
  fixed_rate: '窗口长度',
  stride: '步长',
};

/** 信封/异常里我们真正依赖的字段。 */
interface StructuredError {
  code: number;
  status: number;
  message: string;
  detail?: unknown;
}

/** 鸭子类型识别 `ApiError`（不 import 具体类，避免共享层耦合接口层）。 */
function asStructured(err: unknown): StructuredError | null {
  if (typeof err !== 'object' || err === null) return null;
  const candidate = err as Partial<StructuredError>;
  if (typeof candidate.code !== 'number' || typeof candidate.status !== 'number') return null;
  return {
    code: candidate.code,
    status: candidate.status,
    message: typeof candidate.message === 'string' ? candidate.message : '',
    detail: candidate.detail,
  };
}

/** FastAPI `detail.errors()` → 「字段：原因」，多条用「；」连接。 */
function fieldReasons(detail: unknown): string | undefined {
  if (!Array.isArray(detail)) return undefined;
  const parts: string[] = [];
  for (const item of detail) {
    if (typeof item !== 'object' || item === null) continue;
    const { loc, msg } = item as { loc?: unknown; msg?: unknown };
    if (typeof msg !== 'string' || msg === '') continue;
    // loc 形如 ['body', 'current_a']（列表项会是 ['body', 0, 'x']）：丢掉位置来源与下标，取最后一段字段名。
    const segments = Array.isArray(loc)
      ? loc.filter((seg): seg is string => typeof seg === 'string' && !['body', 'query', 'path', 'header'].includes(seg))
      : [];
    const field = segments.length ? segments[segments.length - 1] : '';
    const label = field ? (FIELD_LABELS[field] ?? field) : '请求参数';
    // ponytail: 直接用 Pydantic 的英文 msg（如 "String should have at most 64 characters"）。
    // 这一路是"绕过后端校验"的兜底提示，正常用户走前端即时校验（中文）；真要汉化再补 msg 映射表。
    parts.push(`${label}：${msg}`);
  }
  return parts.length ? parts.join('；') : undefined;
}

/**
 * 把任意异常翻译成用户可读文案。
 *
 * @param err   捕获到的异常（通常是 `ApiError`）
 * @param scene 场景名，用于拼「{场景}失败…」，如 "登记数据"、"加载数据集"
 */
export function toUserMessage(err: unknown, scene: string): UserError {
  const structured = asStructured(err);
  if (structured === null) {
    if (err instanceof Error && err.message) return { message: `${scene}失败：${err.message}` };
    return { message: `${scene}失败，请重试` };
  }

  // status 0 = fetch 本身失败（client.ts 的网络兜底），不是后端返回的。
  if (structured.status === 0) return { message: `${scene}失败，请检查网络后重试` };

  if (structured.status === 422 || structured.code === 42200) {
    return { message: `${scene}失败：请检查填写内容`, reason: fieldReasons(structured.detail) };
  }
  if (structured.status === 404) return { message: `${scene}失败：该数据不存在或已被删除` };
  if (structured.status === 403) return { message: `${scene}失败：当前账号没有查看权限` };
  // 409 的业务文案本身有意义（"CSV 已存在导入任务"等），保留在原因里不翻译掉。
  if (structured.status === 409) return { message: `${scene}失败`, reason: structured.message || undefined };
  if (structured.status >= 500) return { message: `${scene}失败：服务暂时不可用，请稍后重试` };

  return {
    message: `${scene}失败，请重试`,
    reason: structured.message && structured.message !== '请求失败' ? structured.message : undefined,
  };
}
