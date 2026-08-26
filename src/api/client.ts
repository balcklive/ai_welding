/**
 * src/api/client.ts — 统一请求封装（无 axios，原生 fetch）
 *
 * - base = `/api/v1`：开发环境由 Vite proxy 转发到后端，生产同源，无需切换。
 * - 自动注入 `Authorization: Bearer <token>`（token 存 localStorage，key=`token`）。
 * - 统一解包信封 `{code, message, data}`（§1.3）；`code !== 0` → 抛 `ApiError`。
 * - HTTP 401 → `clearToken()` + `window.location.reload()`（App 重新挂载即回到登录页）。
 */

const BASE = '/api/v1';
const TOKEN_KEY = 'token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  /** 查询参数（任意对象均可；接口/类型别名皆兼容，见 buildQuery 注释）。 */
  query?: object;
  headers?: Record<string, string>;
  /**
   * 为 `true` 时跳过「HTTP 401 → 清 token + 重载」流程（登录失败场景用：
   * 密码错误是业务失败，不应清空会话/刷新页面）。401 仍照常抛 ApiError。
   */
  skipAuth?: boolean;
}

/**
 * 把查询参数对象拼成 URL 查询串（含前导 `?`，无参数返回空串）。
 * - `undefined` / `null` / 空串 跳过；
 * - 数组展开为重复键（`channels=a&channels=b`，对齐后端 `getlist` 读取）。
 * - 参数用 `object`：接口/类型别名均兼容（接口无隐式索引签名，不能赋给
 *   `Record<string, unknown>`），此处仅读取 entries，泛型无需索引签名。
 */
export function buildQuery(params: object): string {
  const parts: string[] = [];
  for (const [key, raw] of Object.entries(params)) {
    if (raw === undefined || raw === null) continue;
    if (Array.isArray(raw)) {
      for (const item of raw) {
        if (item === undefined || item === null) continue;
        parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(item))}`);
      }
    } else if (raw !== '') {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(raw))}`);
    }
  }
  return parts.length > 0 ? `?${parts.join('&')}` : '';
}

/** 解析响应体为信封结构；非 JSON / 空响应兜底为可读消息。 */
async function parseEnvelope(
  res: Response,
): Promise<{ code: number; message: string; data?: unknown }> {
  const text = await res.text();
  if (!text) {
    return { code: -1, message: res.statusText || '空响应' };
  }
  try {
    const parsed = JSON.parse(text) as {
      code?: number;
      message?: string;
      data?: unknown;
    };
    return {
      code: typeof parsed.code === 'number' ? parsed.code : -1,
      message: typeof parsed.message === 'string' ? parsed.message : '请求失败',
      data: parsed.data,
    };
  } catch {
    return { code: -1, message: text };
  }
}

/**
 * 通用请求：解包信封，返回 `data`。
 * 401 → 清 token + 重载；`code !== 0` → 抛 `ApiError(code, message, status)`。
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const url = `${BASE}${path}${buildQuery(options.query ?? {})}`;

  const headers: Record<string, string> = { ...options.headers };
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  let body: BodyInit | null | undefined;
  if (options.body !== undefined) {
    if (options.body instanceof FormData) {
      // multipart（files.uploadFile）：透传 FormData，不设 Content-Type
      // （浏览器自动带 boundary）。
      body = options.body;
    } else {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.body);
    }
  }

  let res: Response;
  try {
    res = await fetch(url, {
      method: options.method ?? 'GET',
      headers,
      body,
    });
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new ApiError(-1, `网络请求失败: ${detail}`, 0);
  }

  const envelope = await parseEnvelope(res);

  if (res.status === 401) {
    if (!options.skipAuth) {
      clearToken();
      window.location.reload();
    }
    throw new ApiError(envelope.code, envelope.message || '未登录或令牌失效', res.status);
  }

  if (envelope.code !== 0) {
    throw new ApiError(envelope.code, envelope.message || '请求失败', res.status);
  }

  return envelope.data as T;
}
