import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  // 只 lint 本工程（前端）源码：
  // - backend/ 是独立 Python 工程，其 .venv 内是第三方 JS（如 matplotlib 的 mpl.js），
  //   扫进来只会产生与本工程无关的告警、并把门禁耗时从秒级拖到 20s+；
  // - .playwright-cli/ 是本地工具产物目录；dist/ 是构建输出。
  { ignores: ['dist', 'backend', '.playwright-cli'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
    },
  }
);
