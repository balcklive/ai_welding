/**
 * src/pages/Login.tsx — 最小登录页（§4.3 / §3.2）。
 *
 * - 两个输入（用户名 / 密码）+ 提交 + 错误提示，无 UI 库；
 * - 调 `auth.login(username, password)`（`skipAuth: true`：密码错误是业务失败，
 *   不会触发 client 的「401 → 清 token + 重载」），失败仅展示 `err.message`；
 * - 成功 → `client.setToken(res.access_token)` 写 localStorage（key=`token`，
 *   后续请求由 client 自动注入 `Authorization`）+ 存 `user`（key=`user`）→ 调 `onSuccess`；
 * - 复用 index.css 现有 `primary-button`；登录特有布局用文件内 `<style>`（类名前缀
 *   `login-`），不污染全局样式、不引 UI 库。
 */
import { useState } from 'react';
import { login } from '../api/auth';
import { ApiError, setToken } from '../api/client';
import type { User } from '../api/types';

const USER_KEY = 'user';

interface LoginProps {
  /** 登录成功（token + user 已落 localStorage）后由外层回调，用于切换渲染。 */
  onSuccess?: () => void;
}

export default function Login({ onSuccess }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('请输入用户名和密码');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await login(username.trim(), password);
      setToken(res.access_token);
      // 供侧边栏用户卡等后续消费；`res.user` 来自 LoginResult（§1.2），无需再调 getMe
      const user: User = res.user;
      localStorage.setItem(USER_KEY, JSON.stringify(user));
      onSuccess?.();
    } catch (err) {
      // ApiError.message 即后端/信封的 message（如「用户名或密码错误」），不刷新页面
      setError(err instanceof ApiError ? err.message : '登录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-brand">
          <div className="login-brand-mark"><img src="/logo-mark.png" alt="三维互联" /></div>
          <div className="login-brand-copy"><strong>焊接工艺分析和建模机器学习平台</strong></div>
        </div>
        <h1>欢迎回来</h1>
        <p className="login-sub">登录焊接工艺分析和建模机器学习平台</p>

        <label className="login-label" htmlFor="login-username">用户名</label>
        <input
          id="login-username"
          className="login-input"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
          autoComplete="username"
          placeholder="请输入用户名"
        />
        <label className="login-label" htmlFor="login-password">密码</label>
        <input
          id="login-password"
          className="login-input"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          placeholder="请输入密码"
        />

        {error && <p className="login-error" role="alert">{error}</p>}

        <button className="primary-button login-submit" type="submit" disabled={loading}>
          {loading ? '登录中…' : '登录'}
        </button>
      </form>
      <style>{`
        .login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px;
          background: #102d35; }
        .login-card { width: 100%; max-width: 380px; padding: 40px 34px 34px;
          background: #fff; border-radius: 14px; box-shadow: 0 24px 60px rgba(0, 0, 0, .28); }
        .login-brand { display: flex; align-items: center; gap: 11px; margin-bottom: 30px; }
        .login-brand-mark { width: 36px; height: 36px; display: grid; place-items: center; }
        .login-brand-mark img { width: 100%; height: 100%; object-fit: contain; }
        .login-brand-copy strong { display: block; color: #16343d; font-size: 16px; letter-spacing: -.2px; }
        .login-card h1 { margin: 0 0 6px; color: #16343d; font-size: 24px; letter-spacing: -1px; }
        .login-sub { margin: 0 0 8px; color: #83979a; font-size: 12px; }
        .login-label { display: block; margin: 18px 0 7px; color: #6f8789; font-size: 11px; }
        .login-input { width: 100%; padding: 11px 12px; border: 1px solid #dce7e5;
          border-radius: 7px; color: #29474d; background: #fff; font-size: 13px; outline: 0; }
        .login-input:focus { border-color: #8cdbc8; box-shadow: 0 0 0 3px rgba(140, 219, 200, .25); }
        .login-error { margin: 16px 0 0; padding: 9px 11px; color: #b3451f;
          background: #fdeee9; border: 1px solid #f6d4c8; border-radius: 6px; font-size: 11px; }
        .login-submit { width: 100%; margin-top: 24px; padding: 12px; font-size: 13px; font-weight: 600; }
        .login-submit:disabled { opacity: .6; cursor: not-allowed; transform: none; }
      `}</style>
    </div>
  );
}
