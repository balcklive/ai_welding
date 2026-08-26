# CLAUDE.md — backend/tests/fixtures/

破坏性测试数据包目录（网页端交互测试用，配套 `docs/破坏性测试指导.md`）。

## 脚本

- `gen_destructive_data.py`：**数据包生成器**——确定性生成全模态测试数据到
  `destructive/`（合法/畸形 CSV 分档、合法/损坏媒体、边界文件 + `MANIFEST.md` 清单）。
  用法：`cd backend && uv run python tests/fixtures/gen_destructive_data.py [输出目录]`。
  依赖：numpy/pandas/scipy/PIL + `imageio-ffmpeg`（自带 ffmpeg 二进制，生成 mp4）。

## 输出

- `destructive/`：生成的数据包（**不入库**，以生成器为唯一来源，可随时重跑）。
  合法 CSV（100/5k/100k/1M 行分档）已用 `signal_ingest.validate_signal` 实测通过；
  畸形 CSV 按预期 fail/warn；合法 mp4 为 H.264 320×240 可播放。

## 坑/限制

- 生成文件较大（`valid_huge_1m.csv` ~80MB、`oversize_101MB.bin` 101MB、解压炸弹 PNG），
  勿提交进 git（保持 untracked）；测试前在本地运行生成器即可。
- 破坏性测试请用本包 + seed 演示数据，**不要用真实生产数据**。
