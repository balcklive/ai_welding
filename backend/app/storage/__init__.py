"""MinIO 对象存储客户端（Task 4）。

对外暴露：

- `get_storage()`：懒加载单例（首次调用构建 `StorageClient`）。
- `StorageClient`：预签名直传 / 代理上传 / 预签名下载 + 对象键规范化。

用法：`from app.storage import get_storage; storage = get_storage()`。
"""

from app.storage.client import StorageClient, get_storage

__all__ = ["StorageClient", "get_storage"]
