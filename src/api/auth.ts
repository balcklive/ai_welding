/**
 * src/api/auth.ts — 认证（§3.1 / §4.2）。
 *
 * - `login` 传 `skipAuth: true`：密码错误返回 HTTP 401 是**业务失败**，
 *   不应触发 client 的「401 → 清 token + 重载」流程（否则登录页无法展示错误）。
 * - token 落库由调用方完成（登录页 / useAuth 经 `client.setToken` 写 localStorage）。
 */
import { request } from './client';
import type { LoginResult, User } from './types';

/** 登录：校验通过返回 JWT + 用户信息（§1.2）。 */
export async function login(
  username: string,
  password: string,
): Promise<LoginResult> {
  return request<LoginResult>('/auth/login', {
    method: 'POST',
    body: { username, password },
    skipAuth: true,
  });
}

/** 当前登录用户（刷新恢复会话）。 */
export async function getMe(): Promise<User> {
  return request<User>('/auth/me');
}
