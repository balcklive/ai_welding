# CLAUDE.md — backend/app/storage/

MinIO 对象存储客户端（Task 4）。桶与连接信息来自 `app.core.config.settings`
（`MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE`/`MINIO_BUCKET`）。
对象键契约见 `docs/OSS存储设计.md` §2（单桶 `aiwelding` + 前缀体系）。

## 脚本

- `__init__.py`：对外 re-export `get_storage`、`StorageClient`（`from app.storage import get_storage`）。
- `client.py`：
  - `normalize_filename(filename)`：规范化文件名——小写、空格→`_`、去 `[a-z0-9._-]`
    之外的字符、折叠连续分隔符、长度 ≤255（超长截断尽量保留扩展名）。中文/特殊字符
    直接剔除，主干清洗空则回退 `file`；结果不含 `/`、`\`、`..`，不以 `.` 开头。
  - `normalize_key(prefix, filename)`：对象键 `{prefix}/{规范化文件名}`；prefix 首尾
    `/` 去除，空 prefix 抛 `ValueError`。
  - `StorageClient`：包 `minio.Minio`。
    - `presign_put(prefix, filename, size, content_type) -> (object_key, upload_url)`：
      大文件直传预签名 PUT URL（30 分钟有效）；`size`/`content_type` 为契约参数
      （Task 9 端点校验用），预签名本身只传 expires（minio SDK 的
      `presigned_put_object` 不支持 size/content_type）。
    - `upload_stream(object_key, fileobj, size, content_type)`：小文件代理上传，
      `put_object(bucket, key, fileobj, size, content_type=...)`。
    - `delete_object(object_key)`：删除单个对象；供 alignment/split 失败回滚清理已写产物。
    - `presign_get(object_key, expires=3600) -> str`：预签名 GET/播放 URL，`expires` 秒
      （长视频可 86400）。
    - `get_object(object_key) -> bytes`：**Task 18**。后端代理读取对象全部字节
      （signal_ingest handler 读 CSV、loader 读 Parquet）。对象不存在抛 `minio.error.S3Error`
      （NoSuchKey），调用方自捕获。`stat_object(object_key) -> int`：返回对象大小字节，
      供大文件阈值预检。
    - `_ensure_bucket()`：各操作首次使用时 `bucket_exists` 否则 `make_bucket`，之后
      记忆（`_bucket_ready`），避免每次操作都多一次往返。
  - `get_storage()`：懒加载单例（模块级 `_storage`），首次调用才构建 `Minio`（构造
    不连网络，仅存配置）。

## 坑/限制

- **测试注入**：`StorageClient(client=FakeMinio())` 可注入假客户端做纯单测，不连
  真实 MinIO（见 `backend/tests/test_storage.py`）。测试也通过
  `monkeypatch.setattr("app.storage.client._storage", ...)` 替换单例。
- **惰性/无网络**：仅 `import app.storage` 或 `get_storage()` 不会触发任何网络调用；
  桶检查只在 `presign_put`/`upload_stream`/`presign_get` 首次使用时发生。因此不调用
  这些方法（如测试环境）无需 MinIO 连接。
- **`presigned_put_object` 签名**（minio 7.2.x）：只有 `(bucket, object_name, expires)`，
  **没有** content_type 参数；不要在 presign_put 里给它传 content_type（会 TypeError）。
  Content-Type 由前端 PUT 时携带（或代理上传时由 `put_object` 的 content_type 落库）。
- **`size` 参数**：`presign_put` 的 `size` 仅作为契约透传（Task 9 校验 Content-Length
  用），不会透传给 minio SDK。
- **业务标识不进规范化**：`normalize_key` 只规范化文件名段，`prefix` 段（类型前缀 +
  业务标识，如 `raw/REG-...`、`uploads/<uuid>`）由调用方按 OSS §2 构造，不做字符清洗。
- **桶保持私有**（OSS §5）：所有访问一律预签名 URL，不开放公开读。
