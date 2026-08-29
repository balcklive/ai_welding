# CLAUDE.md — scripts/

项目级一次性/维护脚本（Python，一律用 uv 运行；依赖按需 `--with` 注入，不进 requirements）。

## 脚本

- `make_logo_assets.py`：把 `data/logo.png` 加工成前端 logo 资源，产物写入 `public/`——
  `logo.png`（完整图含"三维互联"文字）、`logo-mark.png`（裁彩色外接框取圆形图标、补正方形缩到 256px，作 favicon 与侧边栏/登录页品牌标）。
  处理逻辑：近黑像素按最大通道亮度转透明（≤18 全透明、18~70 线性过渡），保留彩色图形与白色文字。
  运行：`uv run --with pillow python scripts/make_logo_assets.py`（幂等，源图更换后重跑即可）。

## 注意事项

- 纯像素逐点处理（424x315 很快），但换大图后如变慢应改 numpy 向量化。
- 产物 `public/` 由 Vite 构建自动拷入 `dist/`，勿手工改产物图。
